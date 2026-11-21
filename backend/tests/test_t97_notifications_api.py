"""T97 알림함·수신 설정 — 규칙 단위 시험(메모리 저장소, DB 없음) + 실제 FastAPI 경로(의존성 교체)."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.routers.notifications import get_notification_inbox_service
from app.schemas.notifications import NotificationPreferencesUpdate
from app.services.notification_inbox import (
    SUMMARY_MAX, InboxRow, MemoryInboxRow, MemoryNotificationInboxRepository, NotificationInboxService,
)
from app.services.notifications import DEFAULT_TEMPLATES, SPECS, Template
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository

NOW = datetime(2026, 11, 14, 3, 0, tzinfo=UTC)
A, B = uuid4(), uuid4()


def add(repo, user, type_="service.maintenance", hours_ago=1, read=False, channel="in_app", status="sent",
        variables=None):
    row = InboxRow(uuid4(), type_, type_, variables if variables is not None else {"window_kst": "02:00~04:00"},
                   NOW - timedelta(hours=hours_ago), NOW if read else None)
    repo.rows[row.delivery_id] = MemoryInboxRow(user, row, channel, status)
    return row.delivery_id


@pytest.fixture
def svc():
    return NotificationInboxService(MemoryNotificationInboxRepository(), clock=lambda: NOW)


def test_inbox_lists_only_own_in_app_sent_rows_newest_first(svc):
    old, new = add(svc.repo, A, hours_ago=5), add(svc.repo, A, "service.policy_change", 1,
                                                   variables={"effective_date": "12월 1일"})
    add(svc.repo, A, channel="email")                 # 이메일 기록은 알림함에 없음
    add(svc.repo, A, status="queued")                 # 아직 전달 전
    add(svc.repo, B)                                  # 남의 알림
    add(svc.repo, A, "unknown.type")                  # 알 수 없는 유형은 노출·집계 안 함
    page = svc.list(A)
    assert [i.notification_id for i in page.items] == [new, old]
    assert page.unread_count == 2
    assert page.items[0].title == DEFAULT_TEMPLATES["service.policy_change"].subject
    assert page.items[0].summary == "12월 1일부터 변경된 정책이 적용됩니다."


def test_summary_never_renders_secret_templates_or_mismatched_variables():
    repo = MemoryNotificationInboxRepository()
    secret = Template("x.secret", "1", True, "제목", "링크 {link}", {"link": "secret"})
    long = Template("service.maintenance", "1", True, "점검", "{window_kst}", {"window_kst": "plain"})
    svc = NotificationInboxService(repo, {"security.password_reset": secret, "service.maintenance": long},
                                   clock=lambda: NOW)
    add(repo, A, "security.password_reset", variables={"link": "https://example.invalid/t?token=abc"})
    add(repo, A, "service.maintenance", hours_ago=2, variables={"window_kst": "가" * 500})
    add(repo, A, "service.maintenance", hours_ago=3, variables={})
    items = svc.list(A).items
    assert items[0].summary == "" and "token" not in items[0].model_dump_json()
    assert len(items[1].summary) == SUMMARY_MAX and items[1].summary.endswith("…")
    assert items[2].summary == ""


def test_mark_read_is_idempotent_and_other_users_ids_are_404(svc):
    mine, theirs = add(svc.repo, A), add(svc.repo, B)
    first = svc.mark_read(A, mine)
    assert first.read_at == NOW
    svc.clock = lambda: NOW + timedelta(hours=1)
    assert svc.mark_read(A, mine).read_at == NOW      # 처음 읽은 시각 유지
    for target in (theirs, uuid4(), add(svc.repo, A, channel="email")):
        with pytest.raises(AppError) as err:
            svc.mark_read(A, target)
        assert err.value.code == ErrorCode.NOT_FOUND
    assert svc.repo.rows[theirs].row.read_at is None


def test_mark_all_read_counts_only_own_unread(svc):
    add(svc.repo, A), add(svc.repo, A, read=True), add(svc.repo, A, hours_ago=2), add(svc.repo, B)
    assert svc.mark_all_read(A).updated == 2
    assert svc.list(A).unread_count == 0 and svc.list(B).unread_count == 1
    assert svc.mark_all_read(A).updated == 0


def test_default_preferences_follow_t95_matrix(svc):
    items = {p.type: p for p in svc.preferences(A).items}
    assert list(items) == list(SPECS)
    for spec in SPECS.values():
        p = items[spec.type]
        assert (p.required, p.consent_policy_code, p.channels) == (spec.required, spec.consent, ["email"])
        assert p.enabled is (True if spec.required else spec.default_on)
    assert items["service.maintenance"].enabled and not items["marketing.newsletter"].enabled
    assert not items["recommendation.new_results"].enabled


def test_update_preferences_per_user_and_required_cannot_be_turned_off(svc):
    upd = NotificationPreferencesUpdate.model_validate
    after = svc.update_preferences(A, upd({"items": [{"type": "marketing.newsletter", "enabled": True},
                                                      {"type": "security.new_login", "enabled": True}]}))
    assert {p.type: p.enabled for p in after.items}["marketing.newsletter"] is True
    assert svc.repo.prefs == {(A, "marketing.newsletter", "email"): True}   # 필수는 저장하지 않음
    assert {p.type: p.enabled for p in svc.preferences(B).items}["marketing.newsletter"] is False
    for body in ({"items": [{"type": "service.maintenance", "enabled": False},
                            {"type": "security.password_reset", "enabled": False}]},
                 {"items": [{"type": "service.maintenance", "enabled": False},
                            {"type": "service.maintenance", "enabled": True}]}):
        with pytest.raises(AppError) as err:
            svc.update_preferences(A, upd(body))
        assert err.value.code == ErrorCode.VALIDATION_FAILED
    assert (A, "service.maintenance", "email") not in svc.repo.prefs           # 일부만 바뀌지 않음


def test_flag_off_by_default_registers_no_route(monkeypatch):
    monkeypatch.delenv("NOTIFICATIONS_API", raising=False)
    assert Settings.from_env().notifications_api is False
    get_settings.cache_clear()
    try:
        paths = {getattr(r, "path", "") for r in create_app().routes}
    finally:
        get_settings.cache_clear()
    assert not any("notification" in p for p in paths)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("NOTIFICATIONS_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    service = NotificationInboxService(MemoryNotificationInboxRepository(), clock=lambda: NOW)
    app.dependency_overrides[get_notification_inbox_service] = lambda: service
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"},
                    raise_server_exceptions=False) as client:
        users = {}
        for email in ("t97-a@example.invalid", "t97-b@example.invalid"):
            r = client.post(f"{API_V1_PREFIX}/auth/signup", json={"email": email, "password": PASSWORD,
                                                                  "display_name": "합성", "consents": CONSENTS})
            assert r.status_code == 201, r.text
            users[email[4]] = (bearer(r.json()["access_token"]), auth.find_local_identity(email).user_id)
        yield client, service, users
    get_settings.cache_clear()


def test_http_contract_and_auth(api):
    client, service, users = api
    (ha, ua), (hb, ub) = users["a"], users["b"]
    base = f"{API_V1_PREFIX}/me"
    for method, path in (("get", "/notifications"), ("post", "/notifications/read-all"),
                         ("post", f"/notifications/{uuid4()}/read"), ("get", "/notification-preferences"),
                         ("put", "/notification-preferences")):
        assert getattr(client, method)(base + path).status_code == 401
    mine, theirs = add(service.repo, UUID(str(ua))), add(service.repo, UUID(str(ub)))
    page = client.get(f"{base}/notifications", headers=ha).json()
    assert page["unread_count"] == 1 and [i["notification_id"] for i in page["items"]] == [str(mine)]
    assert set(page["items"][0]) == {"notification_id", "type", "title", "summary", "created_at", "read_at"}
    assert client.post(f"{base}/notifications/{theirs}/read", headers=ha).status_code == 404
    assert client.post(f"{base}/notifications/not-a-uuid/read", headers=ha).status_code == 422
    one = client.post(f"{base}/notifications/{mine}/read", headers=ha)
    assert one.status_code == 200 and one.json()["read_at"] is not None
    assert client.post(f"{base}/notifications/read-all", headers=hb).json() == {"updated": 1}
    prefs = client.get(f"{base}/notification-preferences", headers=ha).json()
    assert len(prefs["items"]) == len(SPECS)
    bad = client.put(f"{base}/notification-preferences", headers=ha,
                     json={"items": [{"type": "security.password_reset", "enabled": False}]})
    assert bad.status_code == 422
    for body in ({"items": []}, {"items": [{"type": "nope", "enabled": True}]},
                 {"items": [{"type": "marketing.newsletter", "enabled": True, "extra": 1}]}):
        assert client.put(f"{base}/notification-preferences", headers=ha, json=body).status_code == 422
    ok = client.put(f"{base}/notification-preferences", headers=ha,
                    json={"items": [{"type": "marketing.newsletter", "enabled": True}]})
    assert ok.status_code == 200
    assert {p["type"]: p["enabled"] for p in ok.json()["items"]}["marketing.newsletter"] is True
    other = client.get(f"{base}/notification-preferences", headers=hb).json()
    assert {p["type"]: p["enabled"] for p in other["items"]}["marketing.newsletter"] is False
