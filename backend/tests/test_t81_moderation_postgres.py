"""T81 운영 콘텐츠 검수 — 일회용 PostgreSQL 18 + migration 0001·0008·0009·0010 + 최소 권한 앱 역할 + 실제 FastAPI
(ADMIN_MODERATION_API=true).

합성 사용자(security_pg)·합성 조직·합성 공고만 쓴다. 공유 Staging DB 는 쓰지 않는다.

company_posting 결정은 **실제 T125 전이**(CompanyPostingService.decide + T125 SQL 저장소, 기업 공고 관리자 결정과 같은
함수)를 검수 요청과 같은 세션에서 부른다. '검수 건 승인 + organization_job_postings published + job_postings 공개 행'이
한 커밋이고, 게시가 실패하면(company_direct 출처 없음 → 503) 어느 쪽도 바뀌지 않음을 검증한다.
`data_sources('company_direct')` 행은 운영 seed 가 아니라 이 시험의 fixture 데이터다(T125 약관 승인 전).
"""
import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.db import sqlalchemy_url
from app.repositories.moderation import SqlCompanyPostingTransitions, SqlModerationRepository
from app.routers.admin_moderation import get_company_posting_transitions
from app.services import moderation as mod
from app.services.job_postings import ListCursor, derive_cursor_key
from tests.conftest import TEST_SECRET
from tests.security.security_pg import ADMIN, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
API = "/api/v1/admin/moderation-cases"
# organizations: T125 승인이 조직 행을 FOR NO KEY UPDATE 로 잠그므로 UPDATE 권한 필요(0008 이 career_app 에 부여)
WRITE = ("moderation_cases", "moderation_case_events", "audit_events", "organization_job_postings",
         "organization_job_posting_events", "organization_public_companies", "job_postings", "companies",
         "organizations")
SOURCE = ("INSERT INTO career.data_sources (code, name, license_ref) "
          "VALUES ('company_direct', '기업 직접 등록', 't125-terms-test-1')")
SECRET_NOTE = "내부메모-T81-PG-노출금지"


def no_transition():
    return None


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("ADMIN_MODERATION_API", "true")
    gen = disposable_pg(monkeypatch, write_tables=WRITE, migrations=("0001", "0008", "0009", "0010"))
    env = next(gen)
    env.db.execute("INSERT INTO career.user_roles (user_id, role_id) SELECT %s, role_id FROM career.roles "
                   "WHERE code = 'admin'", (USER_B,))                       # 두 번째 관리자(재검토 가드)
    env.engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=4, max_overflow=0)
    try:
        yield env
    finally:
        env.engine.dispose()
        env.client.app.dependency_overrides.pop(get_company_posting_transitions, None)
        next(gen, None)                                                    # 스키마·역할 정리


def service(session, transitions=None):
    effects = {"company_posting": mod.CompanyPostingEffect(transitions)} if transitions else {}
    return mod.ModerationService(SqlModerationRepository(session), ListCursor(derive_cursor_key(TEST_SECRET)), effects)


def submit(pg, target_type, target_id, trigger="PRE_PUBLISH", **kw):
    with Session(pg.engine) as session:
        return service(session).submit(target_type, target_id, trigger, **kw)


def seed_posting(pg, owner=USER_A):
    org = pg.scalar("INSERT INTO career.organizations (name, status, verified_at, created_by_user_id) "
                    "VALUES ('합성 기업 T81', 'active', now(), %s) RETURNING organization_id", owner)
    pg.db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'owner')",
                  (org, owner))
    posting = pg.scalar(
        "INSERT INTO career.organization_job_postings (organization_id, status, title, description, employment_type, "
        "location_text, expires_at, version, created_by_user_id) VALUES (%s, 'pending_review', '합성 백엔드 개발자', "
        "'합성 설명', 'full_time', '서울', now() + interval '30 days', 2, %s) RETURNING posting_id", org, owner)
    case = submit(pg, "company_posting", posting, submitted_by=owner)
    return posting, case


def seed_job_posting(pg):
    return pg.scalar("INSERT INTO career.job_postings (company_id, source_id, title) SELECT company_id, source_id, "
                     "'합성 삭제용 공고' FROM career.companies ORDER BY company_id LIMIT 1 RETURNING job_posting_id")


def assign(pg, case_id, who=ADMIN):
    version = pg.scalar("SELECT version FROM career.moderation_cases WHERE case_id = %s", case_id)
    return pg.client.post(f"{API}/{case_id}/assignment", json={"version": version}, headers=pg.h[who])


def decide(pg, case_id, decision="APPROVE", who=ADMIN, **extra):
    version = pg.scalar("SELECT version FROM career.moderation_cases WHERE case_id = %s", case_id)
    return pg.client.post(f"{API}/{case_id}/decision", json={"version": version, "decision": decision, **extra},
                          headers=pg.h[who])



def snapshot(pg, case_id, posting=None):
    case = pg.db.execute("SELECT status, version, assignee_id FROM career.moderation_cases WHERE case_id = %s",
                         (case_id,)).fetchone()
    counts = tuple(pg.scalar(f"SELECT count(*) FROM career.{t}") for t in (
        "moderation_case_events", "job_postings", "organization_job_posting_events", "organization_public_companies"))
    post = pg.db.execute("SELECT status, version, public_posting_id FROM career.organization_job_postings "
                         "WHERE posting_id = %s", (posting,)).fetchone() if posting else None
    return case, counts, post


# ---------------------------------------------------------------- 큐·상세·권한
def test_queue_detail_and_admin_only(pg):
    posting, case = seed_posting(pg)
    other = submit(pg, "job_posting", seed_job_posting(pg), "REPORT", flags=("PII_PATTERN",))
    assert pg.client.get(API).status_code == 401
    assert pg.client.get(API, headers=pg.h[USER_A]).status_code == 403
    body = pg.client.get(API, headers=pg.h[ADMIN]).json()
    assert [i["case_id"] for i in body["items"]] == [str(other.case_id), str(case.case_id)]    # P2 → P3
    assert body["items"][0]["flags"] == ["PII_PATTERN"] and body["items"][0]["target_summary"] == "합성 삭제용 공고"
    assert body["items"][1]["target_summary"] == "합성 백엔드 개발자" and body["next_cursor"] is None
    page = pg.client.get(API, params={"limit": 1}, headers=pg.h[ADMIN]).json()
    rest = pg.client.get(API, params={"limit": 1, "cursor": page["next_cursor"]}, headers=pg.h[ADMIN]).json()
    assert [i["case_id"] for i in page["items"] + rest["items"]] == [str(other.case_id), str(case.case_id)]
    assert pg.client.get(API, params={"limit": 1, "status": "PENDING", "cursor": page["next_cursor"]},
                         headers=pg.h[ADMIN]).json()["code"] == "INVALID_CURSOR"
    assert [i["case_id"] for i in pg.client.get(API, params={"target_type": "company_posting"},
                                                headers=pg.h[ADMIN]).json()["items"]] == [str(case.case_id)]
    detail = pg.client.get(f"{API}/{case.case_id}", headers=pg.h[ADMIN])
    assert detail.status_code == 200 and detail.json()["submitted_by"] == str(USER_A)
    assert [e["event"] for e in detail.json()["events"]] == ["SUBMIT"]
    assert pg.scalar("SELECT count(*) FROM career.audit_events WHERE action_code = 'admin.content.review' "
                     "AND resource_type = 'moderation_case' AND resource_id = %s AND actor_user_id = %s",
                     case.case_id, ADMIN) == 1                                                  # 열람 감사


def test_duplicate_submit_returns_open_case_and_trigger_rejects_wrong_target(pg):
    jp = seed_job_posting(pg)
    first = submit(pg, "job_posting", jp, "REPORT")
    assert submit(pg, "job_posting", jp, "REPORT").case_id == first.case_id
    assert pg.scalar("SELECT count(*) FROM career.moderation_cases") == 1
    with pytest.raises(AppError) as missing:
        submit(pg, "job_posting", uuid4())                                      # 없는 대상 → FK
    assert missing.value.code == ErrorCode.VALIDATION_FAILED
    with pytest.raises(psycopg_errors().CheckViolation):
        pg.db.execute("INSERT INTO career.moderation_cases (target_type, target_id, review_trigger, priority, due_at) "
                      "VALUES ('job_posting', %s, 'PRE_PUBLISH', 3, now())", (jp,))   # FK 칸 없음 → 트리거 거부
    with pytest.raises(psycopg_errors().CheckViolation):
        pg.db.execute("UPDATE career.moderation_cases SET target_id = %s WHERE case_id = %s", (uuid4(), first.case_id))


def psycopg_errors():
    import psycopg
    return psycopg.errors


def test_assign_guards_and_double_assign(pg):
    posting, case = seed_posting(pg)
    own = submit(pg, "job_posting", seed_job_posting(pg), content_owner_id=ADMIN)
    assert (assign(pg, own.case_id).status_code, assign(pg, own.case_id).json()["code"]) == (403, "FORBIDDEN")
    assert assign(pg, case.case_id, who=USER_A).status_code == 403                          # 일반 사용자
    ok = assign(pg, case.case_id)
    assert ok.status_code == 200 and ok.json()["status"] == "IN_REVIEW" and ok.json()["assignee_id"] == str(ADMIN)
    dup = assign(pg, case.case_id, who=USER_B)
    assert (dup.status_code, dup.json()["code"]) == (409, "CONFLICT")
    stale = pg.client.post(f"{API}/{case.case_id}/assignment/release", json={"version": 1}, headers=pg.h[ADMIN])
    assert (stale.status_code, stale.json()["code"]) == (409, "CONFLICT")
    released = pg.client.post(f"{API}/{case.case_id}/assignment/release", json={"version": 2}, headers=pg.h[USER_B])
    assert released.status_code == 200 and released.json()["status"] == "PENDING"


# ---------------------------------------------------------------- 승인 = 게시 (한 커밋)
def test_approve_publishes_company_posting_in_the_same_commit(pg):
    pg.db.execute(SOURCE)
    posting, case = seed_posting(pg)
    assert assign(pg, case.case_id).status_code == 200
    r = decide(pg, case.case_id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED" and [e["event"] for e in r.json()["events"]][-1] == "APPROVE"
    row = pg.db.execute("SELECT o.status, j.status, j.title FROM career.organization_job_postings o "
                        "JOIN career.job_postings j ON j.job_posting_id = o.public_posting_id WHERE o.posting_id = %s",
                        (posting,)).fetchone()
    assert row == ("published", "published", "합성 백엔드 개발자")
    # 같은 트랜잭션: 검수 이력 시각 = 공개 행 생성 트랜잭션 시각(now()는 트랜잭션 시작 시각)
    assert pg.scalar("SELECT count(*) FROM career.organization_job_posting_events WHERE posting_id = %s "
                     "AND action_code = 'posting.publish' AND actor_user_id = %s", posting, ADMIN) == 1
    again = decide(pg, case.case_id)
    assert (again.status_code, again.json()["code"]) == (409, "APPROVAL_CLOSED")
    assert pg.scalar("SELECT count(*) FROM career.job_postings WHERE title = '합성 백엔드 개발자'") == 1


def test_publish_failure_leaves_case_and_posting_unchanged(pg):
    """company_direct 출처가 없으면 T125 게시가 503 → 검수 건도 IN_REVIEW, 이력·공개 행·회사 행 모두 그대로."""
    posting, case = seed_posting(pg)
    assign(pg, case.case_id)
    before = snapshot(pg, case.case_id, posting)
    audits = pg.scalar("SELECT count(*) FROM career.audit_events")
    r = decide(pg, case.case_id)
    assert (r.status_code, r.json()["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert snapshot(pg, case.case_id, posting) == before
    assert pg.scalar("SELECT count(*) FROM career.audit_events") == audits


def test_reject_with_reason_sets_t125_rejected_and_note_stays_internal(pg):
    posting, case = seed_posting(pg)
    assign(pg, case.case_id)
    assert decide(pg, case.case_id, "REJECT", reason_code="HARMFUL").status_code == 422      # T125 대응 코드 없음
    r = decide(pg, case.case_id, "REJECT", reason_code="OTHER", note=SECRET_NOTE)
    assert r.status_code == 200 and r.json()["reason_code"] == "OTHER" and SECRET_NOTE not in r.text
    assert pg.db.execute("SELECT status, reason_code, public_posting_id FROM career.organization_job_postings "
                         "WHERE posting_id = %s", (posting,)).fetchone() == ("rejected", "other", None)
    assert pg.scalar("SELECT reviewer_note FROM career.moderation_cases WHERE case_id = %s", case.case_id) == SECRET_NOTE
    assert pg.scalar("SELECT count(*) FROM career.moderation_case_events WHERE reason_code = %s", SECRET_NOTE) == 0


def test_without_a_company_posting_transition_the_decision_is_refused(pg):
    pg.client.app.dependency_overrides[get_company_posting_transitions] = no_transition
    posting, case = seed_posting(pg)
    assign(pg, case.case_id)
    before = snapshot(pg, case.case_id, posting)
    r = decide(pg, case.case_id)
    assert (r.status_code, r.json()["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert snapshot(pg, case.case_id, posting) == before


# ---------------------------------------------------------------- 동시성
def _race(pg, case_id, version, transitions_factory):
    barrier, results = threading.Barrier(2), []

    def worker():
        with Session(pg.engine) as session:
            barrier.wait()
            try:
                service(session, transitions_factory(session) if transitions_factory else None).decide(
                    ADMIN, frozenset({"admin"}), case_id, version, "APPROVE")
                results.append("ok")
            except AppError as exc:
                results.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(map(str, results))


def test_concurrent_double_approve_publishes_once(pg):
    pg.db.execute(SOURCE)
    posting, case = seed_posting(pg)
    assign(pg, case.case_id)
    version = pg.scalar("SELECT version FROM career.moderation_cases WHERE case_id = %s", case.case_id)
    assert _race(pg, case.case_id, version, SqlCompanyPostingTransitions) == sorted(["ok", "APPROVAL_CLOSED"])
    assert pg.scalar("SELECT count(*) FROM career.job_postings WHERE title = '합성 백엔드 개발자'") == 1
    assert pg.scalar("SELECT count(*) FROM career.moderation_case_events WHERE case_id = %s AND event = 'APPROVE'",
                     case.case_id) == 1


def test_concurrent_double_approve_without_content_effect(pg):
    case = submit(pg, "job_posting", seed_job_posting(pg), "REPORT")
    assign(pg, case.case_id)
    assert _race(pg, case.case_id, 2, None) == sorted(["ok", "APPROVAL_CLOSED"])
    assert pg.scalar("SELECT status FROM career.moderation_cases WHERE case_id = %s", case.case_id) == "APPROVED"


# ---------------------------------------------------------------- 대상 삭제 트리거
def test_deleting_the_target_closes_open_cases_and_keeps_decided_ones(pg):
    jp_open, jp_done = seed_job_posting(pg), seed_job_posting(pg)
    open_case = submit(pg, "job_posting", jp_open, "REPORT")
    done = submit(pg, "job_posting", jp_done, "REPORT")
    assign(pg, done.case_id)
    assert decide(pg, done.case_id).status_code == 200
    pg.db.execute("DELETE FROM career.job_postings WHERE job_posting_id IN (%s, %s)", (jp_open, jp_done))
    rows = dict(pg.db.execute("SELECT case_id, status || ':' || coalesce(close_reason, '') FROM career.moderation_cases"
                              ).fetchall())
    assert rows == {open_case.case_id: "CLOSED:TARGET_DELETED", done.case_id: "APPROVED:"}
    detail = pg.client.get(f"{API}/{open_case.case_id}", headers=pg.h[ADMIN]).json()
    assert detail["target_id"] == str(jp_open) and detail["target_summary"] is None
    assert detail["events"][-1] == {**detail["events"][-1], "event": "CLOSE", "actor_user_id": None,
                                    "reason_code": "TARGET_DELETED", "to_status": "CLOSED"}
