"""T142 내 데이터 반출 — 일회용 PostgreSQL 18 + migration 0004~0006 + 최소 권한 앱 역할 + 실제 FastAPI
(PERSONAL_DATA_REQUESTS_API=true, 운영 배선 `build_sql_service`, 시계만 시험용).

합성 사용자 A·B(security_pg)만 씁니다. 공유 Staging DB 는 쓰지 않습니다.
요청 → worker 처리 → 1회 다운로드 → 만료, 타인 404, 취소, 재인증 필수, 토큰 해시 저장, 동시 접수 1건.
"""
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends

from app.core.security import hash_password
from app.db import get_db
from app.personal_data_worker import run_once
from app.routers.personal_data_requests import build_sql_service, get_data_request_service
from tests.security.security_pg import ROOT, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
DDLS = tuple((ROOT / "database/migrations" / name).read_text(encoding="utf-8") for name in (
    "0004_job_applications.sql", "0005_notifications.sql", "0006_personal_data_requests.sql"))
WRITE_TABLES = ("data_subject_requests", "data_reauth_grants", "data_export_downloads", "data_export_artifacts",
                "audit_events")
API = "/api/v1/me/data-requests"
SECRET = "synthetic-Passw0rd-142"
ORG = "합성 회사 T142"


class Clock:
    def __init__(self):
        self.now = datetime.now(UTC).replace(microsecond=0)

    def __call__(self):
        return self.now


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("PERSONAL_DATA_REQUESTS_API", "true")
    for env in disposable_pg(monkeypatch, write_tables=WRITE_TABLES, extra_sql=DDLS):
        for uid, email in ((USER_A, "t86-a@example.invalid"), (USER_B, "t86-b@example.invalid")):
            env.db.execute("INSERT INTO career.auth_identities (user_id, provider, subject, password_hash) "
                           "VALUES (%s, 'local', %s, %s)", (uid, email, hash_password(SECRET)))
        env.db.execute("INSERT INTO career.user_experiences (user_id, organization, title) VALUES (%s, %s, '개발자')",
                       (USER_A, ORG))
        clock = Clock()
        app = env.client.app

        def service(db=Depends(get_db)):
            return build_sql_service(db, clock=clock)

        app.dependency_overrides[get_data_request_service] = service
        env.clock = clock
        env.worker = lambda: _worker(app, clock)
        yield env
        app.dependency_overrides.clear()


def _worker(app, clock):
    with app.state.db_session_factory() as session:
        return run_once(build_sql_service(session, clock=clock))


def reauth(pg, user, password=SECRET):
    return pg.client.post(f"{API}/reauth", json={"password": password}, headers=pg.h[user])


def with_reauth(pg, user):
    r = reauth(pg, user)
    assert r.status_code == 200, r.text
    return {**pg.h[user], "X-Reauth-Token": r.json()["reauth_token"]}


def export(pg, user):
    return pg.client.post(f"{API}/exports", headers=with_reauth(pg, user))


def link(pg, user, rid):
    return pg.client.post(f"{API}/exports/{rid}/download-link", headers=with_reauth(pg, user))


def download(pg, user, token):
    return pg.client.post(f"{API}/download", json={"token": token}, headers=pg.h[user])


def status(pg, user, rid):
    return pg.client.get(f"{API}/exports/{rid}", headers=pg.h[user])


def test_reauth_is_required_and_tokens_are_stored_hashed(pg):
    assert pg.client.post(f"{API}/exports", headers=pg.h[USER_A]).status_code == 403
    r = pg.client.post(f"{API}/exports", headers={**pg.h[USER_A], "X-Reauth-Token": "x" * 43})
    assert r.status_code == 403 and r.headers["X-Reauth-Required"] == "true"
    assert reauth(pg, USER_A, "wrong-Passw0rd-000").status_code == 401
    headers = with_reauth(pg, USER_A)
    # 다른 사용자 세션으로 옮긴 재인증 토큰은 무효
    assert pg.client.post(f"{API}/exports", headers={**pg.h[USER_B], "X-Reauth-Token": headers["X-Reauth-Token"]}
                          ).status_code == 403
    assert pg.client.post(f"{API}/exports", headers=headers).status_code == 202
    hashes = [r[0] for r in pg.db.execute("SELECT token_hash FROM career.data_reauth_grants").fetchall()]
    assert hashes and headers["X-Reauth-Token"] not in hashes and all(len(h) == 64 for h in hashes)
    # 10분이 지나면 다시 재인증
    pg.clock.now += timedelta(minutes=10)
    assert pg.client.post(f"{API}/exports/{uuid.uuid4()}/download-link", headers=headers).status_code == 403
    actions = {r[0] for r in pg.db.execute("SELECT action_code FROM career.audit_events").fetchall()}
    assert {"privacy.dsr.reauth", "privacy.dsr.reauth.denied", "privacy.export.request"} <= actions


def test_create_process_download_once_then_expired(pg):
    r = export(pg, USER_A)
    assert r.status_code == 202 and r.headers["Cache-Control"] == "no-store", r.text
    rid = r.json()["request_id"]
    assert status(pg, USER_A, rid).json()["status"] == "received"
    assert link(pg, USER_A, rid).status_code == 409                          # 완료 전
    assert pg.worker() == {"retried": 0, "processed": 1, "expired": 0}
    body = status(pg, USER_A, rid).json()
    assert body["status"] == "completed" and body["size_bytes"] > 0 and body["expires_at"]
    assert pg.scalar("SELECT count(*) FROM career.data_export_artifacts") == 1
    token = link(pg, USER_A, rid).json()["token"]
    assert pg.scalar("SELECT count(*) FROM career.data_export_downloads WHERE token_hash = %s", token) == 0
    first = download(pg, USER_A, token)
    assert first.status_code == 200 and "attachment" in first.headers["Content-Disposition"]
    bundle = json.loads(first.content)
    assert bundle["data"]["career"]["experiences"][0]["organization"] == ORG
    assert bundle["data"]["account"]["user"][0]["user_id"] == str(USER_A)
    for key in ("password_hash", "refresh_token_hash", "email_canonical", "storage_key"):
        assert f'"{key}"' not in first.text, key
    assert download(pg, USER_A, token).status_code == 404                     # 1회용
    assert status(pg, USER_A, rid).json()["status"] == "expired"
    assert pg.scalar("SELECT count(*) FROM career.data_export_artifacts") == 0  # 묶음 삭제
    assert pg.scalar("SELECT artifact_sha256 FROM career.data_subject_requests WHERE request_id = %s", rid)
    actions = [r[0] for r in pg.db.execute(
        "SELECT action_code FROM career.audit_events WHERE resource_id = %s ORDER BY occurred_at", (rid,)).fetchall()]
    for expected in ("privacy.export.request", "privacy.dsr.start", "privacy.dsr.complete", "privacy.dsr.download",
                     "privacy.dsr.expire"):
        assert expected in actions, expected


def test_artifact_expires_after_24_hours(pg):
    rid = export(pg, USER_A).json()["request_id"]
    pg.worker()
    token = link(pg, USER_A, rid).json()["token"]
    pg.clock.now += timedelta(minutes=11)
    assert download(pg, USER_A, token).status_code == 404                     # 링크 10분
    pg.clock.now += timedelta(hours=24)
    assert pg.worker()["expired"] == 1
    assert status(pg, USER_A, rid).json()["status"] == "expired"
    assert pg.scalar("SELECT count(*) FROM career.data_export_artifacts") == 0
    assert pg.scalar("SELECT count(*) FROM career.data_reauth_grants") == 0   # 지난 허가 정리
    assert link(pg, USER_A, rid).status_code == 409


def test_other_user_gets_404_everywhere_and_burns_the_token(pg):
    rid = export(pg, USER_A).json()["request_id"]
    pg.worker()
    token = link(pg, USER_A, rid).json()["token"]
    assert status(pg, USER_B, rid).status_code == 404
    assert pg.client.post(f"{API}/exports/{rid}/cancel", headers=pg.h[USER_B]).status_code == 404
    assert link(pg, USER_B, rid).status_code == 404
    assert download(pg, USER_B, token).status_code == 404
    assert pg.client.get(API, headers=pg.h[USER_B]).json()["items"] == []
    assert download(pg, USER_A, token).status_code == 404                     # 타인 시도로 소모됨
    assert download(pg, USER_A, link(pg, USER_A, rid).json()["token"]).status_code == 200
    assert pg.scalar("SELECT count(*) FROM career.audit_events WHERE action_code = 'privacy.dsr.download.denied'") == 2


def test_cancel_only_before_processing_and_duplicate_is_409(pg):
    rid = export(pg, USER_A).json()["request_id"]
    assert export(pg, USER_A).status_code == 409                              # 열린 요청 1건
    r = pg.client.post(f"{API}/exports/{rid}/cancel", headers=pg.h[USER_A])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert pg.client.post(f"{API}/exports/{rid}/cancel", headers=pg.h[USER_A]).status_code == 409
    rid2 = export(pg, USER_A).json()["request_id"]
    pg.worker()
    assert pg.client.post(f"{API}/exports/{rid2}/cancel", headers=pg.h[USER_A]).status_code == 409
    items = pg.client.get(API, headers=pg.h[USER_A]).json()["items"]
    assert sorted(i["status"] for i in items) == ["cancelled", "completed"]


def test_concurrent_creates_produce_exactly_one(pg):
    factory = pg.client.app.state.db_session_factory
    results, barrier = [], threading.Barrier(6)

    def go():
        with factory() as session:
            service = build_sql_service(session, clock=pg.clock)
            barrier.wait()
            try:
                results.append(service.create_export(USER_A).request_id)
            except Exception as exc:  # noqa: BLE001
                results.append(str(getattr(exc, "code", exc)))

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(isinstance(r, uuid.UUID) for r in results) == 1, results
    assert results.count("CONFLICT") == 5, results
    assert pg.scalar("SELECT count(*) FROM career.data_subject_requests WHERE user_id = %s", USER_A) == 1
