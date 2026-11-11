"""T87 동의 철회·탈퇴·보존 E2E (실제 PostgreSQL 18 일회용 DB, 합성 사용자 A·B 만).

기존 시험과 겹치지 않게, **시스템을 가로지르는 전파**만 확인합니다.
- 이미 있는 것: 동의 이력·원자성·동시성(test_privacy_postgres), 행동 데이터 철회·재동의·만료 purge(test_behavior_data_postgres),
  분석 worker 의 동의 재확인(test_document_analyses_postgres), 문서 삭제 worker 재시도(test_documents).
- 여기서 추가:
  1) 사용자 참조 FK **전부**의 삭제/보존 분류 게이트 — 새 개인 데이터 표가 분류 없이 생기면 실패
  2) A 의 철회 → 행동 수집 0 · 신규 분석 차단, B 는 그대로
  3) A 의 탈퇴 요청 → 모든 비공개 경로 401(경로 목록 재사용), 문서 접근 차단, 영수증 행, B 는 그대로
  4) 탈퇴 접수 중간 실패 → 아무것도 바뀌지 않음 → 재시도 성공(1건)
  5) (HOLD 기능의 사전 검증) 물리 삭제를 일회용 DB 에서 흉내 → 분류표대로 삭제·익명화, B 불변
실제 회원 데이터·공유 DB 는 사용하지 않습니다. 물리 삭제 작업(purge job)은 미구현·정책 미승인(HOLD)입니다.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg import sql

from tests.security.security_inventory import protected
from tests.security.security_pg import USER_A, USER_B, disposable_pg, requires_pg
from tests.test_behavior_events_postgres import ENABLED

pytestmark = requires_pg

# 사용자 행이 지워질 때(향후 purge) 각 개인 데이터가 어떻게 되는지 — 0001 FK 기준 검토 결과.
# DELETE = 사용자와 함께 삭제, ANONYMIZE = 행은 보존하고 사용자 참조만 NULL (감사·통계·영수증)
RETENTION_MAP = {
    "account_deletion_requests.user_id": "ANONYMIZE",   # 탈퇴 영수증: 처리 이력은 남김
    "agent_runs.user_id": "DELETE",
    "agent_tool_approvals.approver_user_id": "ANONYMIZE",
    "ai_usage_records.user_id": "ANONYMIZE",            # 익명 집계 (FR-ADM-005 수용 기준 3)
    "audit_events.actor_user_id": "ANONYMIZE",          # 감사 기록 보존 (T83 DRAFT)
    "auth_identities.user_id": "DELETE",
    "auth_sessions.user_id": "DELETE",
    "behavior_events.user_id": "DELETE",
    "match_evaluations.user_id": "DELETE",
    "password_reset_tokens.user_id": "DELETE",
    "recommendation_feedback.user_id": "DELETE",
    "recommendation_runs.user_id": "DELETE",
    "retrieval_runs.user_id": "DELETE",
    "skill_gap_assessments.user_id": "DELETE",
    "user_consents.user_id": "DELETE",
    "user_documents.owner_user_id": "DELETE",            # 분석·청크(검색 인덱스)·인용은 문서 FK CASCADE
    "user_experiences.user_id": "DELETE",
    "user_job_bookmarks.user_id": "DELETE",
    "user_profiles.user_id": "DELETE",
    "user_projects.user_id": "DELETE",
    "user_roles.granted_by_user_id": "ANONYMIZE",
    "user_roles.user_id": "DELETE",
    "user_segment_assignments.user_id": "DELETE",
    "user_skills.user_id": "DELETE",
    "user_target_roles.user_id": "DELETE",
}
ACTION = {"c": "DELETE", "n": "ANONYMIZE", "r": "BLOCK", "a": "BLOCK"}
# user_documents: 문서 조회·분석 요청이 행 잠금(FOR UPDATE/SHARE)을 써서 UPDATE 권한이 필요 (최소 권한 시험으로 확인)
WRITES = ("user_consents", "behavior_events", "account_deletion_requests", "users", "auth_sessions", "user_documents",
          "document_analyses", "model_versions")   # 분석 요청이 Mock 모델 버전 행을 처음 한 번 등록
POLICIES = [
    "INSERT INTO career.consent_policies(policy_code,version,is_required,content_url,effective_at) "
    "VALUES('behavior_tracking','v1',false,'https://example.invalid/bt', now() - interval '1 day'),"
    "('llm_processing','v1',false,'https://example.invalid/llm', now() - interval '1 day')",
]


@pytest.fixture
def pg(monkeypatch):
    """문서 파일 저장소는 T51 PG 시험과 같은 메모리 저장소로 대체(파일 내용은 시험 대상 아님, OS 무관)."""
    from app.routers.documents import get_document_storage
    from tests.test_document_analyses_postgres import MemoryStorage
    gen = disposable_pg(monkeypatch, write_tables=WRITES, migrations=("0001", "0002"), extra_sql=POLICIES)
    env = next(gen)
    storage = MemoryStorage()
    env.client.app.dependency_overrides[get_document_storage] = lambda: storage
    try:
        yield env
    finally:
        env.client.app.dependency_overrides.clear()
        gen.close()


def consent(pg, user, code, granted):
    response = pg.client.post("/api/v1/me/consents", headers=pg.h[user],
                              json={"policy_code": code, "policy_version": "v1", "granted": granted})
    assert response.status_code in (200, 201), response.text


def seed_personal_data(pg, user):
    """사용자별 개인 데이터 (합성). 문서·분석·청크(검색 인덱스)·행동·경험·북마크·감사·사용량."""
    db = pg.db
    doc = uuid4()
    db.execute("INSERT INTO career.user_documents (document_id, owner_user_id, kind, original_filename, mime_type, "
               "size_bytes, storage_key, checksum_sha256, status) VALUES (%s,%s,'resume','synthetic.pdf',"
               "'application/pdf',10,%s,%s,'ready')", (doc, user, secrets.token_hex(32), hashlib.sha256(b"x").hexdigest()))
    db.execute("INSERT INTO career.document_chunks (document_id, chunk_index, content_hash, index_ref) "
               "VALUES (%s, 0, %s, 'synthetic-index-ref')", (doc, "0" * 64))
    db.execute("INSERT INTO career.behavior_events (user_id, event_code, metadata) VALUES (%s,'posting.view','{}')", (user,))
    db.execute("INSERT INTO career.user_experiences (user_id, organization, title) VALUES (%s,'합성','x')", (user,))
    db.execute("INSERT INTO career.audit_events (actor_user_id, action_code, resource_type) VALUES (%s,'user.profile.update','user_profile')",
               (user,))
    db.execute("INSERT INTO career.ai_usage_records (user_id, provider_model, feature_code) VALUES (%s,'mock','agent')", (user,))
    return doc


def rows_of(pg, user):
    out = {}
    for ref in RETENTION_MAP:
        table, column = ref.split(".")
        out[ref] = pg.scalar(sql.SQL("SELECT count(*) FROM career.{} WHERE {} = %s").format(
            sql.Identifier(table), sql.Identifier(column)).as_string(pg.db), user)
    out["document_chunks(via documents)"] = pg.scalar(
        "SELECT count(*) FROM career.document_chunks c JOIN career.user_documents d USING (document_id) "
        "WHERE d.owner_user_id=%s", user)
    return out


# ---------------------------------------------------------------- 1) retention classification gate
def test_every_user_foreign_key_has_a_reviewed_retention_class(pg):
    rows = pg.db.execute("""
        SELECT c.conrelid::regclass::text, a.attname, c.confdeltype
        FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f' AND c.confrelid = 'career.users'::regclass""").fetchall()
    actual = {f"{table.removeprefix('career.')}.{column}": ACTION[action] for table, column, action in rows}
    assert actual == RETENTION_MAP, {"unclassified": set(actual) - set(RETENTION_MAP),
                                     "changed": {k: (v, actual.get(k)) for k, v in RETENTION_MAP.items() if actual.get(k) != v}}
    assert "BLOCK" not in actual.values(), "a RESTRICT FK would make account purge fail"


# ---------------------------------------------------------------- 2) consent withdrawal propagation
def test_withdrawal_stops_new_processing_for_a_only(pg):
    pg.client.app.state.behavior_event_settings = ENABLED
    for user in (USER_A, USER_B):
        consent(pg, user, "behavior_tracking", True)
        consent(pg, user, "llm_processing", True)
        seed_personal_data(pg, user)
    event = lambda: {"event_id": str(uuid4()), "event_code": "posting.view",  # noqa: E731
                     "event_at": datetime.now(UTC).isoformat(), "metadata": {"job_posting_id": "jp_1", "list_position": 1}}
    assert pg.client.post("/api/v1/me/behavior-events", headers=pg.h[USER_A], json=event()).status_code in (200, 201, 202)

    consent(pg, USER_A, "behavior_tracking", False)
    consent(pg, USER_A, "llm_processing", False)
    assert pg.scalar("SELECT count(*) FROM career.behavior_events WHERE user_id=%s", USER_A) == 0
    assert pg.scalar("SELECT count(*) FROM career.behavior_events WHERE user_id=%s", USER_B) == 1
    for _ in range(3):
        pg.client.post("/api/v1/me/behavior-events", headers=pg.h[USER_A], json=event())
    assert pg.scalar("SELECT count(*) FROM career.behavior_events WHERE user_id=%s", USER_A) == 0, "new processing 0"

    doc_a = pg.scalar("SELECT document_id FROM career.user_documents WHERE owner_user_id=%s", USER_A)
    blocked = pg.client.post(f"/api/v1/documents/{doc_a}/analyses", headers=pg.h[USER_A],
                             json={"analysis_type": "skill_extraction"})
    assert blocked.status_code == 403 and blocked.json()["code"] == "CONSENT_REQUIRED"
    assert pg.scalar("SELECT count(*) FROM career.document_analyses WHERE document_id=%s", doc_a) == 0
    doc_b = pg.scalar("SELECT document_id FROM career.user_documents WHERE owner_user_id=%s", USER_B)
    assert pg.client.post(f"/api/v1/documents/{doc_b}/analyses", headers=pg.h[USER_B],
                          json={"analysis_type": "skill_extraction"}).status_code == 202
    history = [r[0] for r in pg.db.execute("SELECT granted FROM career.user_consents WHERE user_id=%s AND "
                                           "policy_code='llm_processing' ORDER BY recorded_at", (USER_A,)).fetchall()]
    assert history == [True, False], "append-only consent history keeps the withdrawal evidence"


# ---------------------------------------------------------------- 3) deletion request propagation
def test_deletion_request_cuts_every_protected_route_and_keeps_b(pg):
    for user in (USER_A, USER_B):
        seed_personal_data(pg, user)
    before_b = rows_of(pg, USER_B)
    receipt = pg.client.post("/api/v1/me/deletion-request", headers=pg.h[USER_A], json={"confirmation": "DELETE"})
    assert receipt.status_code in (200, 201, 202), receipt.text
    body = receipt.json()
    assert body["status"] == "requested" and "requested_at" in body
    assert str(USER_A) not in receipt.text and "@example" not in receipt.text

    assert pg.scalar("SELECT status FROM career.users WHERE user_id=%s", USER_A) == "disabled"
    assert pg.scalar("SELECT count(*) FROM career.auth_sessions WHERE user_id=%s AND revoked_at IS NULL", USER_A) == 0
    assert pg.scalar("SELECT count(*) FROM career.account_deletion_requests WHERE user_id=%s AND status='requested'", USER_A) == 1
    for route in protected():
        response = pg.client.request(route.method, route.url(), headers=pg.h[USER_A])
        assert response.status_code == 401, f"{route}: {response.status_code}"
    doc_a = pg.scalar("SELECT document_id FROM career.user_documents WHERE owner_user_id=%s", USER_A)
    assert pg.client.get(f"/api/v1/documents/{doc_a}", headers=pg.h[USER_B]).status_code == 404
    # 접수만 구현: 물리 삭제 전이므로 데이터는 아직 남아 있다(보존 기간·purge 미승인 — HOLD)
    assert rows_of(pg, USER_A)["user_documents.owner_user_id"] == 1
    assert pg.client.get("/api/v1/me", headers=pg.h[USER_B]).status_code == 200
    assert rows_of(pg, USER_B) == before_b
    # Finding F87-1 (현재 동작 고정): 탈퇴 접수·동의 철회는 audit_events 에 남지 않는다.
    # T83 계약(DRAFT)은 privacy.deletion.request / privacy.consent.update 를 기록 대상으로 제안 — 승인·구현 후 이 단정을 뒤집는다.
    assert pg.scalar("SELECT count(*) FROM career.audit_events WHERE action_code LIKE 'privacy.%%'") == 0
    # Finding F87-2: 접수 후에는 계정이 비활성이라 본인이 처리 상태(영수증)를 다시 조회할 수 없다 (취소는 503 HOLD)
    assert pg.client.get("/api/v1/me/deletion-request", headers=pg.h[USER_A]).status_code == 401


def test_deletion_intake_failure_changes_nothing_and_retry_recovers(pg):
    pg.db.execute(sql.SQL("REVOKE UPDATE ON career.auth_sessions FROM {}").format(sql.Identifier(pg.role)))
    failed = pg.client.post("/api/v1/me/deletion-request", headers=pg.h[USER_A], json={"confirmation": "DELETE"})
    assert failed.status_code == 503
    assert pg.scalar("SELECT count(*) FROM career.account_deletion_requests WHERE user_id=%s", USER_A) == 0
    assert pg.scalar("SELECT status FROM career.users WHERE user_id=%s", USER_A) == "active"
    assert pg.client.get("/api/v1/me", headers=pg.h[USER_A]).status_code == 200, "partial failure left no half state"
    pg.db.execute(sql.SQL("GRANT UPDATE ON career.auth_sessions TO {}").format(sql.Identifier(pg.role)))
    retried = pg.client.post("/api/v1/me/deletion-request", headers=pg.h[USER_A], json={"confirmation": "DELETE"})
    assert retried.status_code in (200, 201, 202)
    assert pg.scalar("SELECT count(*) FROM career.account_deletion_requests WHERE user_id=%s", USER_A) == 1
    assert pg.client.get("/api/v1/me", headers=pg.h[USER_A]).status_code == 401


# ---------------------------------------------------------------- 5) simulated purge (HOLD feature, disposable DB only)
def test_simulated_physical_purge_follows_the_retention_map(pg):
    for user in (USER_A, USER_B):
        seed_personal_data(pg, user)
    pg.client.post("/api/v1/me/deletion-request", headers=pg.h[USER_A], json={"confirmation": "DELETE"})
    before_b = rows_of(pg, USER_B)
    anonymized_before = {t: pg.scalar(f"SELECT count(*) FROM career.{t}") for t in
                         ("audit_events", "ai_usage_records", "account_deletion_requests")}
    pg.db.execute("DELETE FROM career.users WHERE user_id=%s", (USER_A,))   # 일회용 DB 에서만 — purge 흉내
    after_a = rows_of(pg, USER_A)
    assert all(count == 0 for count in after_a.values()), after_a
    for table, count in anonymized_before.items():
        assert pg.scalar(f"SELECT count(*) FROM career.{table}") == count, f"{table} rows retained (anonymized)"
    assert pg.scalar("SELECT count(*) FROM career.account_deletion_requests WHERE user_id IS NULL AND status='requested'") == 1
    assert pg.scalar("SELECT count(*) FROM career.document_chunks WHERE index_ref='synthetic-index-ref'") == 1, "only B's chunk"
    assert rows_of(pg, USER_B) == before_b
