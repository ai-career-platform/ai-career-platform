"""T125·T128 제안 DDL을 일회용 PostgreSQL에 적용해 제약을 확인한다(승인 전 migration 아님).

`T125_T128_ADMIN_URL`(관리자 접속, 예: postgresql://user@127.0.0.1:55496/postgres)이 있을 때만 실행.
매번 `t125_ddl_<임의>` DB를 새로 만들고 0001~0003 + T122 + T125 + T128 을 적용한 뒤 끝나면 지운다.
공유·Staging DB에는 접속하지 않는다(loopback 만).
"""

import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
ADMIN_URL = os.environ.get("T125_T128_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="T125_T128_ADMIN_URL not set (disposable PostgreSQL only)")
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ["0001_initial_schema.sql", "0002_deletion_request_unscheduled.sql",
              "0003_market_metric_skill_dimension.sql"]
PROPOSED = ["T122_organizations.sql", "T125_company_postings.sql", "T128_public_portfolio.sql"]

# backend/app/repositories/job_postings.py 의 _is_open 과 같은 공개 조건
PUBLIC_OPEN = "status = 'published' AND (expires_at IS NULL OR expires_at > now())"


@pytest.fixture
def db():
    host = ADMIN_URL.split("@", 1)[-1].split("/", 1)[0]
    assert host.split(":")[0] in {"127.0.0.1", "localhost"}, "loopback only"
    name = f"t125_ddl_{secrets.token_hex(4)}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE SCHEMA career")
            for m in MIGRATIONS:
                conn.execute((ROOT / "database" / "migrations" / m).read_text(encoding="utf-8"))
            for p in PROPOSED:
                conn.execute((ROOT / "database" / "proposed" / p).read_text(encoding="utf-8"))
            yield conn
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def user(conn, n):
    uid = uuid.uuid4()
    conn.execute("INSERT INTO career.users (user_id, email, email_canonical, display_name) VALUES (%s, %s, %s, 'u')",
                 (uid, f"synthetic{n}@example.com", f"synthetic{n}@example.com"))
    return uid


def rejects(conn, sql, params=(), error=None):
    with pytest.raises(error or psycopg.errors.IntegrityError):
        with conn.transaction():
            conn.execute(sql, params)


# ------------------------------------------------------------------ T125
def org(conn, owner):
    oid = conn.execute("INSERT INTO career.organizations (name, status, verified_at, created_by_user_id) "
                       "VALUES ('Synthetic Org', 'active', now(), %s) RETURNING organization_id", (owner,)).fetchone()[0]
    conn.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'owner')",
                 (oid, owner))
    return oid


def posting(conn, oid, status="draft", **extra):
    complete = {"description": "d", "employment_type": "full_time", "location_text": "Seoul",
                "expires_at": "2099-01-01T00:00:00Z"} if status != "draft" else {}
    cols = {"organization_id": oid, "status": status, "title": "Synthetic engineer", **complete, **extra}
    names, marks = ", ".join(cols), ", ".join(["%s"] * len(cols))
    return conn.execute(f"INSERT INTO career.organization_job_postings ({names}) VALUES ({marks}) RETURNING posting_id",
                        list(cols.values())).fetchone()[0]


def public_company(conn, oid):
    src = conn.execute("INSERT INTO career.data_sources (code, name, license_ref) VALUES "
                       "('company_direct', '기업 직접 등록', 'organization-posting-terms-v1 (PROPOSED)') "
                       "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING source_id").fetchone()[0]
    cid = conn.execute("INSERT INTO career.companies (name, source_id) VALUES ('Synthetic Org', %s) RETURNING company_id",
                       (src,)).fetchone()[0]
    conn.execute("INSERT INTO career.organization_public_companies (organization_id, company_id) VALUES (%s, %s)",
                 (oid, cid))
    return src, cid


def publish(conn, oid, pid):
    """SQL 저장소가 할 posting.publish: 같은 트랜잭션에서 공개 행 생성 + 기업 공고 연결."""
    src, cid = public_company(conn, oid)
    with conn.transaction():
        jp = conn.execute("INSERT INTO career.job_postings (company_id, source_id, title, description, employment_type,"
                          " location_text, status, published_at, expires_at) SELECT %s, %s, title, description,"
                          " employment_type, location_text, 'published', now(), expires_at"
                          " FROM career.organization_job_postings WHERE posting_id = %s RETURNING job_posting_id",
                          (cid, src, pid)).fetchone()[0]
        conn.execute("UPDATE career.organization_job_postings SET status='published', published_at=now(),"
                     " public_posting_id=%s, version=version+1 WHERE posting_id=%s", (jp, pid))
    return jp


def public_rows(conn):
    return conn.execute(f"SELECT count(*) FROM career.job_postings WHERE {PUBLIC_OPEN}").fetchone()[0]


def test_posting_state_check_matches_state_machine(db):
    machine = json.loads((ROOT / "docs" / "enterprise" / "t125_posting_state_machine.json").read_text(encoding="utf-8"))
    oid = org(db, user(db, 1))
    for state in machine["states"]:
        if state in {"published", "closed", "expired", "taken_down"}:
            continue                                    # 게시 이력이 필요한 상태는 아래 흐름 시험에서
        extra = {"reason_code": "other", "reason_note": "n"} if state == "rejected" else {}
        posting(db, oid, state, **extra)
    rejects(db, "INSERT INTO career.organization_job_postings (organization_id, status, title) VALUES (%s, 'approved', 't')",
            (oid,))


def test_drafts_and_review_never_reach_public_predicate(db):
    oid = org(db, user(db, 2))
    draft = posting(db, oid)
    pending = posting(db, oid, "pending_review")
    rejected = posting(db, oid, "rejected", reason_code="duplicate_posting")
    assert public_rows(db) == 0                         # 공개 표에 행 자체가 없다
    src, cid = public_company(db, oid)
    jp = db.execute("INSERT INTO career.job_postings (company_id, source_id, title, status, published_at) "
                    "VALUES (%s, %s, 't', 'closed', now()) RETURNING job_posting_id", (cid, src)).fetchone()[0]
    for pid in (draft, pending, rejected):              # 게시 전 상태는 공개 행에 연결될 수 없다
        rejects(db, "UPDATE career.organization_job_postings SET public_posting_id = %s WHERE posting_id = %s",
                (jp, pid))
    # 검수 요청 이후에는 필수 항목 완비
    rejects(db, "INSERT INTO career.organization_job_postings (organization_id, status, title) "
                "VALUES (%s, 'pending_review', 't')", (oid,))
    # 반려·내림 사유 코드 목록, 'other' 반려는 설명 필수, 초안에는 사유 없음
    rejects(db, "UPDATE career.organization_job_postings SET status='rejected', reason_code='fraud_suspected' "
                "WHERE posting_id = %s", (pending,))
    rejects(db, "UPDATE career.organization_job_postings SET status='rejected', reason_code='other' "
                "WHERE posting_id = %s", (pending,))
    rejects(db, "UPDATE career.organization_job_postings SET reason_code='other' WHERE posting_id = %s", (draft,))
    rejects(db, "UPDATE career.organization_job_postings SET apply_url='http://x.example' WHERE posting_id = %s",
            (draft,))


def test_publish_close_keeps_public_row_in_sync(db):
    oid = org(db, user(db, 3))
    pid = posting(db, oid, "pending_review")
    jp = publish(db, oid, pid)
    assert public_rows(db) == 1
    # 기업 공고만 닫고 공개 행을 그대로 두면 커밋 시 거부(제약 트리거)
    rejects(db, "UPDATE career.organization_job_postings SET status='closed' WHERE posting_id = %s", (pid,))
    with db.transaction():                              # 같은 트랜잭션에서 둘 다 닫으면 허용(순서 무관)
        db.execute("UPDATE career.organization_job_postings SET status='taken_down', reason_code='legal_request' "
                   "WHERE posting_id = %s", (pid,))
        db.execute("UPDATE career.job_postings SET status='closed' WHERE job_posting_id = %s", (jp,))
    assert public_rows(db) == 0
    # 게시 이력 없이 종료 상태 금지, 공개 행 하나에 기업 공고 하나
    rejects(db, "INSERT INTO career.organization_job_postings (organization_id, status, title, description, "
                "employment_type, location_text, expires_at) VALUES (%s,'closed','t','d','intern','s','2099-01-01')",
            (oid,))
    other = posting(db, oid, "pending_review")
    rejects(db, "UPDATE career.organization_job_postings SET status='published', published_at=now(), "
                "public_posting_id=%s WHERE posting_id=%s", (jp, other), psycopg.errors.UniqueViolation)


def test_one_open_revision_same_org_and_no_public_link(db):
    owner = user(db, 4)
    oid, oid2 = org(db, owner), org(db, user(db, 5))
    pid = posting(db, oid, "pending_review")
    jp = publish(db, oid, pid)
    rev = posting(db, oid, revision_of=pid)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            posting(db, oid, revision_of=pid)
    rejects(db, "INSERT INTO career.organization_job_postings (organization_id, title, revision_of) VALUES (%s,'t',%s)",
            (oid2, pid))                                # 다른 조직 원본은 가리킬 수 없다
    # 수정본 승인 = 원본 내용 갱신 + 수정본은 공개 행 없이 closed(merged). 수정본은 공개 행을 가질 수 없다.
    with db.transaction():
        db.execute("UPDATE career.organization_job_postings SET status='closed', published_at=now(), description='d',"
                   " employment_type='intern', location_text='s', expires_at='2099-01-01',"
                   " reason_note='merged into original' WHERE posting_id=%s", (rev,))
        db.execute("UPDATE career.organization_job_postings SET version=version+1 WHERE posting_id=%s", (pid,))
    db.execute("UPDATE career.job_postings SET status='closed' WHERE job_posting_id=%s", (jp,))
    db.execute("UPDATE career.organization_job_postings SET status='closed' WHERE posting_id=%s", (pid,))
    rejects(db, "UPDATE career.organization_job_postings SET public_posting_id=NULL, status='published' "
                "WHERE posting_id=%s", (pid,))          # 원본 게시 상태는 공개 행 필수
    posting(db, oid, revision_of=pid)                   # 이전 수정본이 닫히면 새 수정본 허용


def test_posting_events_and_member_deletion(db):
    owner = user(db, 6)
    oid = org(db, owner)
    pid = posting(db, oid, created_by_user_id=owner)
    db.execute("INSERT INTO career.organization_job_posting_events (posting_id, organization_id, action_code, "
               "actor_user_id) VALUES (%s, %s, 'posting.draft_create', %s)", (pid, oid, owner))
    rejects(db, "INSERT INTO career.organization_job_posting_events (posting_id, organization_id, action_code) "
                "VALUES (%s, %s, 'posting.bogus')", (pid, oid))
    rejects(db, "INSERT INTO career.organization_job_posting_events (posting_id, organization_id, action_code, "
                "actor_user_id) VALUES (%s, %s, 'system.expire', %s)", (pid, oid, owner))
    db.execute("DELETE FROM career.users WHERE user_id = %s", (owner,))     # 탈퇴 → 사람 연결만 익명화
    assert db.execute("SELECT created_by_user_id FROM career.organization_job_postings WHERE posting_id=%s",
                      (pid,)).fetchone()[0] is None
    assert db.execute("SELECT actor_user_id FROM career.organization_job_posting_events").fetchone()[0] is None
    rejects(db, "DELETE FROM career.organizations WHERE organization_id = %s", (oid,))   # 공고 있는 조직은 삭제 불가


# ------------------------------------------------------------------ T128
def experience(conn, uid):
    return conn.execute("INSERT INTO career.user_experiences (user_id, organization, title) VALUES (%s,'o','t') "
                        "RETURNING experience_id", (uid,)).fetchone()[0]


def test_selection_fields_and_consent(db):
    uid = user(db, 10)
    rejects(db, "INSERT INTO career.public_profile_selections (user_id, fields) VALUES (%s, ARRAY['email'])", (uid,))
    rejects(db, "INSERT INTO career.public_profile_selections (user_id, fields) VALUES (%s, ARRAY['documents'])", (uid,))
    rejects(db, "INSERT INTO career.public_profile_selections (user_id, confirmed_version) VALUES (%s, 1)", (uid,))
    db.execute("INSERT INTO career.public_profile_selections (user_id, fields, version) "
               "VALUES (%s, ARRAY['headline','skills'], 2)", (uid,))
    rejects(db, "UPDATE career.public_profile_selections SET confirmed_version = 1 WHERE user_id = %s", (uid,))
    db.execute("UPDATE career.public_profile_selections SET confirmed_version = 2 WHERE user_id = %s", (uid,))
    db.execute("INSERT INTO career.consent_policies (policy_code, version, is_required, content_url, effective_at) "
               "VALUES ('public_profile', 'proposal-1', false, 'https://example.invalid/t128', now())")
    cid = db.execute("INSERT INTO career.user_consents (user_id, policy_code, policy_version, granted) "
                     "VALUES (%s, 'public_profile', 'proposal-1', true) RETURNING consent_id", (uid,)).fetchone()[0]
    db.execute("INSERT INTO career.public_profile_consent_records (consent_id, user_id, selection_version) "
               "VALUES (%s, %s, 2)", (cid, uid))


def test_selected_items_must_be_owned_and_follow_deletion(db):
    uid, other = user(db, 11), user(db, 12)
    mine, theirs = experience(db, uid), experience(db, other)
    db.execute("INSERT INTO career.public_profile_selections (user_id, fields) VALUES (%s, ARRAY['experience.title'])",
               (uid,))
    db.execute("INSERT INTO career.public_profile_selected_experiences (user_id, experience_id) VALUES (%s,%s)",
               (uid, mine))
    rejects(db, "INSERT INTO career.public_profile_selected_experiences (user_id, experience_id) VALUES (%s,%s)",
            (uid, theirs))                              # 남의 경력은 선택할 수 없다
    db.execute("DELETE FROM career.user_experiences WHERE experience_id = %s", (mine,))
    assert db.execute("SELECT count(*) FROM career.public_profile_selected_experiences").fetchone()[0] == 0


def test_links_store_hash_only_with_ttl_and_cascade(db):
    uid = user(db, 13)
    rejects(db, "INSERT INTO career.public_profile_links (user_id, token_hash, expires_at) "
                "VALUES (%s, 'plain-token', now() + interval '1 day')", (uid,))
    rejects(db, "INSERT INTO career.public_profile_links (user_id, token_hash, expires_at) "
                "VALUES (%s, %s, now() + interval '91 days')", (uid, "a" * 64))
    digest = hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
    db.execute("INSERT INTO career.public_profile_links (user_id, token_hash, expires_at) "
               "VALUES (%s, %s, now() + interval '30 days')", (uid, digest))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            db.execute("INSERT INTO career.public_profile_links (user_id, token_hash, expires_at) "
                       "VALUES (%s, %s, now() + interval '30 days')", (uid, digest))
    db.execute("INSERT INTO career.public_profile_selections (user_id, fields) VALUES (%s, ARRAY['bio'])", (uid,))
    db.execute("DELETE FROM career.users WHERE user_id = %s", (uid,))       # 탈퇴 → 선택·링크 즉시 삭제
    for table in ("public_profile_links", "public_profile_selections"):
        assert db.execute(f"SELECT count(*) FROM career.{table}").fetchone()[0] == 0
