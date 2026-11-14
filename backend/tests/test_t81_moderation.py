"""T81 운영 콘텐츠 검수 API — 메모리 저장소 + 실제 FastAPI 라우터·인증(ADMIN_MODERATION_API=true).

큐(필터·정렬·cursor·overdue), 상세·이력·열람 감사, 담당·해제, 승인·반려(사유 검증), 가드(자기 콘텐츠·담당자 아님·
재검토 최초 결정자), 409 구분, 콘텐츠 효과 없는 결정 거절(503, 변경 없음), company_posting 은 T125 전이와 함께만
바뀜(메모리 T125 서비스), 메모·사유 원문이 응답·로그에 없음. 실제 PostgreSQL 은 test_t81_moderation_postgres.py.
"""
import logging
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.routers.admin_moderation import get_company_posting_transitions, get_moderation_service
from app.services import company_postings as cp
from app.services import moderation as mod
from app.services.company_accounts import CompanyAccountService, Member, MemoryCompanyRepository, Organization
from app.services.job_postings import ListCursor, derive_cursor_key
from app.services.mail import MemoryMailSender
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository

API = f"{API_V1_PREFIX}/admin/moderation-cases"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
SECRET_NOTE = "내부메모-원문-T81-노출금지"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class MemoryTransitions:
    """T125 메모리 서비스의 decide 를 그대로 부르는 전이(실제 SQL 전이는 T125 저장소가 제공)."""

    def __init__(self, service: cp.CompanyPostingService):
        self.service, self.calls = service, []

    def lock_posting(self, posting_id):
        posting = self.service.repo.postings.get(posting_id)
        return posting.version if posting else None

    def decide(self, *args):
        self.calls.append(args)
        return self.service.decide(*args)


class World:
    def __init__(self, app, client, auth, store, clock):
        self.app, self.c, self.auth, self.store, self.clock = app, client, auth, store, clock
        self.transitions = None

    def user(self, email, admin=False):
        r = self.c.post(f"{API_V1_PREFIX}/auth/signup", json={"email": email, "password": PASSWORD,
                                                              "display_name": "합성", "consents": CONSENTS})
        uid = self.auth.find_local_identity(email).user_id
        if admin:
            self.auth.grant_role(uid, "admin")
            r = self.c.post(f"{API_V1_PREFIX}/auth/login", json={"email": email, "password": PASSWORD})
        return uid, bearer(r.json()["access_token"])

    def service(self):
        effects = {"company_posting": mod.CompanyPostingEffect(self.transitions)} if self.transitions else {}
        return mod.ModerationService(mod.MemoryModerationRepository(self.store),
                                     ListCursor(derive_cursor_key(TEST_SECRET)), effects, clock=self.clock)

    def submit(self, target_type="document_analysis", trigger="PRE_PUBLISH", target_id=None, **kw):
        return self.service().submit(target_type, target_id or uuid.uuid4(), trigger, **kw)

    def get(self, case, who=None):
        return self.c.get(f"{API}/{case.case_id}", headers=who or self.ha)

    def assign(self, case, who=None, version=None):
        version = version or self.store.cases[case.case_id].version
        return self.c.post(f"{API}/{case.case_id}/assignment", json={"version": version}, headers=who or self.ha)

    def decide(self, case, decision="APPROVE", who=None, version=None, **extra):
        version = version or self.store.cases[case.case_id].version
        return self.c.post(f"{API}/{case.case_id}/decision", json={"version": version, "decision": decision, **extra},
                           headers=who or self.ha)


@pytest.fixture
def w(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("ADMIN_MODERATION_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    world_ref = {}
    app.dependency_overrides[get_moderation_service] = lambda: world_ref["w"].service()
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        world = World(app, client, auth, mod.MemoryModerationStore(), Clock())
        world_ref["w"] = world
        world.a, world.ha = world.user("ops-a@example.com", admin=True)
        world.b, world.hb = world.user("ops-b@example.com", admin=True)
        world.u, world.hu = world.user("seeker@example.com")
        yield world
    get_settings.cache_clear()


def test_flag_off_registers_no_moderation_routes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("ADMIN_MODERATION_API", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        paths = {r.path for r in create_app().routes}
        assert not [p for p in paths if "moderation" in p]
    finally:
        get_settings.cache_clear()


def test_requires_login_and_admin_role(w):
    case = w.submit()
    assert w.c.get(API).status_code == 401
    assert w.c.get(API, headers=w.hu).status_code == 403
    assert w.c.get(f"{API}/{case.case_id}", headers=w.hu).status_code == 403
    assert w.assign(case, who=w.hu).status_code == 403
    assert w.c.get(f"{API}/{uuid.uuid4()}", headers=w.ha).status_code == 404


def test_queue_order_filters_overdue_and_cursor(w):
    late = w.submit("job_posting", "REPORT", priority=1)          # due NOW+24h
    pre = [w.submit() for _ in range(3)]                          # P3, due NOW+72h
    w.clock.now = NOW + timedelta(hours=30)                        # P1 건만 기한 지남
    body = w.c.get(API, headers=w.ha).json()
    assert [i["case_id"] for i in body["items"]][0] == str(late.case_id)
    first = body["items"][0]
    assert first["overdue"] is True and first["target_summary"] == "채용공고" and first["trigger"] == "REPORT"
    assert set(first) == {"case_id", "target_type", "target_id", "target_summary", "trigger", "status", "priority",
                          "assignee_id", "due_at", "overdue", "flags", "report_count", "version", "created_at"}
    assert [i["case_id"] for i in w.c.get(API, params={"overdue": "true"}, headers=w.ha).json()["items"]] == [
        str(late.case_id)]
    assert len(w.c.get(API, params={"priority": 3}, headers=w.ha).json()["items"]) == 3
    assert w.c.get(API, params={"target_type": "company"}, headers=w.ha).json()["items"] == []
    assert w.c.get(API, params={"status": "NOPE"}, headers=w.ha).status_code == 422
    assert w.c.get(API, params={"priority": 4}, headers=w.ha).status_code == 422
    # cursor: 2개씩 → 중복·누락 없이 4개, 다른 필터에 쓰면 400
    page1 = w.c.get(API, params={"limit": 2}, headers=w.ha).json()
    page2 = w.c.get(API, params={"limit": 2, "cursor": page1["next_cursor"]}, headers=w.ha).json()
    seen = [i["case_id"] for i in page1["items"] + page2["items"]]
    assert sorted(seen) == sorted(str(c.case_id) for c in [late, *pre]) and page2["next_cursor"] is None
    bad = w.c.get(API, params={"limit": 2, "priority": 3, "cursor": page1["next_cursor"]}, headers=w.ha)
    assert (bad.status_code, bad.json()["code"]) == (400, "INVALID_CURSOR")


def test_assign_then_approve_records_history_and_audit(w):
    case = w.submit(submitted_by=None)
    detail = w.get(case).json()
    assert detail["status"] == "PENDING" and [e["event"] for e in detail["events"]] == ["SUBMIT"]
    assert detail["events"][0]["actor_user_id"] is None                                     # system
    assigned = w.assign(case)
    assert assigned.status_code == 200 and assigned.json()["status"] == "IN_REVIEW"
    assert assigned.json()["assignee_id"] == str(w.a) and assigned.json()["version"] == 2
    again = w.assign(case, who=w.hb)
    assert (again.status_code, again.json()["code"]) == (409, "CONFLICT")
    not_assignee = w.decide(case, who=w.hb)
    assert (not_assignee.status_code, not_assignee.json()["code"]) == (403, "FORBIDDEN")
    stale = w.decide(case, version=1)
    assert (stale.status_code, stale.json()["code"]) == (409, "CONFLICT")
    ok = w.decide(case)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "APPROVED" and body["first_decider_id"] == str(w.a) and body["decided_by"] == str(w.a)
    assert body["assignee_id"] is None and body["reason_code"] is None
    assert [(e["event"], e["from_status"], e["to_status"]) for e in body["events"]] == [
        ("SUBMIT", None, "PENDING"), ("ASSIGN", "PENDING", "IN_REVIEW"), ("APPROVE", "IN_REVIEW", "APPROVED")]
    closed = w.decide(case, version=body["version"])
    assert (closed.status_code, closed.json()["code"]) == (409, "APPROVAL_CLOSED")
    assert (w.assign(case).status_code, w.assign(case).json()["code"]) == (409, "APPROVAL_CLOSED")
    # 감사: 열람 1 + 배정 1 + 승인 1, 모두 admin.content.review / moderation_case
    audit = [a for a in w.store.audit if a["resource_id"] == case.case_id]
    assert len(audit) == 3 and {a["action_code"] for a in audit} == {"admin.content.review"}


def test_reject_validation_and_note_never_returned_or_logged(w, caplog):
    case = w.submit()
    w.assign(case)
    for extra in ({}, {"reason_code": "NOPE"}, {"reason_code": "OTHER"}, {"reason_code": "OTHER", "note": "   "},
                  {"reason_code": "HARMFUL", "note": "x" * 501}):
        r = w.decide(case, "REJECT", **extra)
        assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_FAILED"), extra
    assert w.decide(case, "APPROVE", reason_code="HARMFUL").status_code == 422
    assert w.decide(case, "APPROVE", note="메모").status_code == 422
    assert w.c.post(f"{API}/{case.case_id}/decision", json={"version": 2, "decision": "APPROVE", "x": 1},
                    headers=w.ha).status_code == 422
    with caplog.at_level(logging.DEBUG):
        r = w.decide(case, "REJECT", reason_code="OTHER", note=SECRET_NOTE)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED" and r.json()["reason_code"] == "OTHER"
    assert SECRET_NOTE not in r.text and SECRET_NOTE not in w.get(case).text
    assert SECRET_NOTE not in caplog.text
    assert w.store.cases[case.case_id].reviewer_note == SECRET_NOTE                      # 관리자 전용 저장
    assert w.store.events[-1].reason_code == "OTHER"


def test_self_content_and_first_decider_guards(w):
    own = w.submit(content_owner_id=w.a)
    r = w.assign(own)
    assert (r.status_code, r.json()["code"]) == (403, "FORBIDDEN")
    assert w.assign(own, who=w.hb).status_code == 200
    submitted = w.submit("retrieval_run", submitted_by=w.b)
    assert w.assign(submitted, who=w.hb).status_code == 403
    # 재검토 단계(APPEALED, appeal_count=1, 최초 결정자 A): A 는 배정 불가, B 는 가능 → 해제하면 다시 APPEALED
    appealed = w.submit("company")
    w.store.cases[appealed.case_id] = replace(w.store.cases[appealed.case_id], status="APPEALED", appeal_count=1,
                                              first_decider_id=w.a, reason_code="HARMFUL", decided_by=w.a)
    r = w.assign(appealed)
    assert (r.status_code, r.json()["code"]) == (403, "FORBIDDEN")
    assert w.assign(appealed, who=w.hb).status_code == 200
    released = w.c.post(f"{API}/{appealed.case_id}/assignment/release",
                        json={"version": w.store.cases[appealed.case_id].version}, headers=w.ha)
    assert released.status_code == 200 and released.json()["status"] == "APPEALED"
    assert released.json()["events"][-1]["event"] == "RELEASE_APPEAL" and released.json()["assignee_id"] is None


def test_release_returns_to_pending_and_needs_in_review(w):
    case = w.submit()
    r = w.c.post(f"{API}/{case.case_id}/assignment/release", json={"version": 1}, headers=w.ha)
    assert (r.status_code, r.json()["code"]) == (409, "CONFLICT")
    w.assign(case)
    r = w.c.post(f"{API}/{case.case_id}/assignment/release", json={"version": 2}, headers=w.hb)
    assert r.status_code == 200 and r.json()["status"] == "PENDING" and r.json()["events"][-1]["event"] == "RELEASE"


@pytest.mark.parametrize("target_type,trigger,decision", [
    ("job_posting", "PRE_PUBLISH", "APPROVE"),        # 공개 효과 미구현 → 결정하지 않음
    ("shared_document", "PRE_PUBLISH", "APPROVE"),
    ("job_posting", "REPORT", "REJECT"),              # 게시 중단 효과 미구현(계약 §5 OPEN)
    ("document_analysis", "REPORT", "REJECT"),        # 결과 숨김 미구현
    ("company_posting", "PRE_PUBLISH", "APPROVE"),    # T125 SQL 전이 없음
    ("company_posting", "PRE_PUBLISH", "REJECT"),
])
def test_decision_needing_a_missing_content_effect_changes_nothing(w, target_type, trigger, decision):
    case = w.submit(target_type, trigger)
    w.assign(case)
    before = (w.store.cases[case.case_id], len(w.store.events), len(w.store.audit))
    extra = {"reason_code": "HARMFUL"} if decision == "REJECT" else {}
    if target_type == "company_posting" and decision == "REJECT":
        extra = {"reason_code": "DUPLICATE"}
    r = w.decide(case, decision, **extra)
    assert (r.status_code, r.json()["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert (w.store.cases[case.case_id], len(w.store.events), len(w.store.audit)) == before


def test_decisions_without_content_effect_are_allowed(w):
    reject_pre = w.submit("job_posting", "PRE_PUBLISH")            # 게시 전 반려 = 비공개 유지
    keep = w.submit("job_posting", "REPORT")                       # 신고 후 승인 = 게시 유지
    for case, decision, extra in [(reject_pre, "REJECT", {"reason_code": "RIGHTS_UNCLEAR"}), (keep, "APPROVE", {})]:
        w.assign(case)
        assert w.decide(case, decision, **extra).status_code == 200


def test_content_effect_matrix():
    assert mod.content_effect("company_posting", "PRE_PUBLISH", "APPROVE") == "target"
    assert mod.content_effect("company_posting", "PRE_PUBLISH", "REJECT") == "target"
    assert mod.content_effect("company_posting", "REPORT", "APPROVE") == "none"
    assert mod.content_effect("agent_run", "PRE_PUBLISH", "APPROVE") == "none"
    assert mod.content_effect("job_posting", "PRE_PUBLISH", "REJECT") == "none"
    assert mod.content_effect("match_evaluation", "REPORT", "REJECT") == "target"


# ---------------------------------------------------------------- company_posting ↔ T125 (메모리)
@pytest.fixture
def t125(w):
    clock = w.clock
    accounts = CompanyAccountService(MemoryCompanyRepository(), users=None, mail=MemoryMailSender(), clock=clock)
    org_id, owner = uuid.uuid4(), uuid.uuid4()
    accounts.repo.organizations[org_id] = Organization(org_id, "합성 기업", "active", None, owner, NOW)
    accounts.repo.members[(org_id, owner)] = Member(org_id, owner, "owner", NOW)
    public = cp.MemoryPublicPostings()
    service = cp.CompanyPostingService(accounts, cp.MemoryPostingRepository(), public, clock=clock)

    def pending():
        posting = cp.CompanyPosting(uuid.uuid4(), org_id, "pending_review", "백엔드 개발자", description="설명",
                                    employment_type="full_time", location_text="서울",
                                    expires_at=NOW + timedelta(days=30), version=2, created_by=owner, updated_at=NOW)
        service.repo.postings[posting.posting_id] = posting
        return posting, w.submit("company_posting", target_id=posting.posting_id, content_owner_id=None,
                                 submitted_by=owner)

    w.transitions = MemoryTransitions(service)
    return service, public, pending, org_id


def test_company_posting_approve_publishes_through_the_t125_transition(w, t125):
    service, public, pending, _ = t125
    posting, case = pending()
    w.assign(case)
    r = w.decide(case)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    published = service.repo.postings[posting.posting_id]
    assert published.status == "published" and published.public_posting_id in public.rows
    assert [row["job_posting_id"] for row in public.published()] == [published.public_posting_id]
    assert service.repo.audit[-1]["action_code"] == "posting.publish"           # T125 자기 감사도 같은 경로
    assert w.transitions.calls[0][3:7] == ("approve", None, None, 2)


def test_company_posting_reject_maps_reason_and_unmapped_reason_changes_nothing(w, t125):
    service, public, pending, _ = t125
    posting, case = pending()
    w.assign(case)
    before = (w.store.cases[case.case_id], service.repo.postings[posting.posting_id])
    r = w.decide(case, "REJECT", reason_code="HARMFUL")                          # T125 대응 코드 없음
    assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_FAILED")
    assert (w.store.cases[case.case_id], service.repo.postings[posting.posting_id]) == before
    r = w.decide(case, "REJECT", reason_code="PERSONAL_DATA")
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    rejected = service.repo.postings[posting.posting_id]
    assert (rejected.status, rejected.reason_code, rejected.public_posting_id) == ("rejected", "personal_contact_info",
                                                                                  None)
    assert public.published() == []


def test_t125_refusal_rolls_back_the_case(w, t125):
    """T125 가 거절(관리자가 그 조직 멤버 → 403)하면 검수 건도 IN_REVIEW 그대로, 이력·감사 추가 없음."""
    service, public, pending, org_id = t125
    posting, case = pending()
    service.accounts.repo.members[(org_id, w.a)] = Member(org_id, w.a, "admin", NOW)
    w.assign(case)
    before = (w.store.cases[case.case_id], len(w.store.events), len(w.store.audit))
    r = w.decide(case)
    assert (r.status_code, r.json()["code"]) == (403, "FORBIDDEN")
    assert (w.store.cases[case.case_id], len(w.store.events), len(w.store.audit)) == before
    assert service.repo.postings[posting.posting_id].status == "pending_review" and public.published() == []


def test_company_posting_withdrawn_meanwhile_is_a_conflict(w, t125):
    service, public, pending, _ = t125
    posting, case = pending()
    w.assign(case)
    service.repo.postings[posting.posting_id] = replace(posting, status="draft", version=3)   # 기업이 검수 요청 철회
    r = w.decide(case)
    assert (r.status_code, r.json()["code"]) == (409, "CONFLICT")
    assert w.store.cases[case.case_id].status == "IN_REVIEW" and public.published() == []


def test_concurrent_double_approve_only_one_wins(w, t125):
    service, public, pending, _ = t125
    posting, case = pending()
    w.assign(case)
    version = w.store.cases[case.case_id].version
    barrier, codes = threading.Barrier(2), []

    def worker():
        barrier.wait()
        try:
            w.service().decide(w.a, frozenset({"admin"}), case.case_id, version, "APPROVE")
            codes.append("ok")
        except Exception as exc:  # noqa: BLE001 — AppError 코드 수집
            codes.append(getattr(exc, "code", exc))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(map(str, codes)) == sorted(["ok", str(mod.ErrorCode.APPROVAL_CLOSED)])
    assert len(public.published()) == 1 and len(w.transitions.calls) == 1


def test_submit_returns_the_existing_open_case(w):
    target = uuid.uuid4()
    first = w.submit("agent_run", "REPORT", target_id=target)
    again = w.submit("agent_run", "REPORT", target_id=target)
    other = w.submit("agent_run", "PRE_PUBLISH", target_id=target)
    assert again.case_id == first.case_id and other.case_id != first.case_id
    assert first.priority == 2 and first.due_at == NOW + timedelta(hours=48)
    with pytest.raises(mod.AppError):
        w.submit("user_profile")


def test_real_dependency_has_no_company_posting_transition_without_t125_sql():
    assert get_company_posting_transitions(db=None) is None
