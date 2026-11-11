"""T122 기업 조직·소속·초대 데이터 계약(PROPOSED) — 일회용 PostgreSQL 18 에서 제안 DDL 제약을 검증한다.

정식 migration 이 아니다(database/proposed). 공유 Staging DB 에 적용하지 않는다.
DDL 없이도 도는 문서·DTO 일치 시험은 항상 실행된다.
"""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DDL_PATH = ROOT / "database" / "proposed" / "T122_organizations.sql"
CONTRACT = ROOT / "docs" / "enterprise" / "T122_COMPANY_MEMBERSHIP_CONTRACT.md"
OPENAPI = ROOT / "docs" / "enterprise" / "t122_openapi_proposal.yaml"
MATRIX = json.loads((ROOT / "docs" / "enterprise" / "t121_role_matrix.json").read_text(encoding="utf-8"))


def token_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


# ------------------------------------------------------------------ 문서·DTO 일치(항상 실행)
def test_ddl_is_marked_proposed_and_not_in_migrations():
    assert DDL_PATH.read_text(encoding="utf-8").startswith("-- PROPOSED (T122)")
    assert not list((ROOT / "database" / "migrations").glob("*organization*"))


def test_dto_enums_match_ddl_and_t121_roles():
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    ddl = DDL_PATH.read_text(encoding="utf-8")
    assert schemas["OrganizationStatus"]["enum"] == ["pending", "active", "suspended", "closed", "rejected"]
    assert schemas["MemberRole"]["enum"] == ["owner", "member"]
    assert schemas["InvitationStatus"]["enum"] == ["pending", "accepted", "revoked", "expired"]
    for value in schemas["OrganizationStatus"]["enum"] + schemas["InvitationStatus"]["enum"]:
        assert f"'{value}'" in ddl
    assert {f"company_{r}" for r in schemas["MemberRole"]["enum"]} == {
        r for r, meta in MATRIX["roles"].items() if meta["scope"] == "organization"}
    # T121 조직 상태 규칙에 있는 상태는 DTO 에도 있다
    assert set(MATRIX["org_status_rules"]) <= set(schemas["OrganizationStatus"]["enum"])


def test_invitation_dto_never_exposes_token_hash_or_other_members_email():
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    for name, schema in spec["components"]["schemas"].items():
        props = schema.get("properties", {})
        assert "token_hash" not in props, name
    assert "email_masked" in spec["components"]["schemas"]["Invitation"]["properties"]
    assert "email" not in spec["components"]["schemas"]["Invitation"]["properties"]
    assert "PROPOSED" in spec["info"]["title"]


def test_contract_document_covers_ttl_multi_membership_deletion_and_audit():
    text = CONTRACT.read_text(encoding="utf-8")
    for needle in ("TTL", "다중 소속", "ON DELETE CASCADE", "audit_events", "마지막 owner", "30일", "PROPOSED"):
        assert needle in text, needle


# ------------------------------------------------------------------ 일회용 PostgreSQL
from tests.security.security_pg import ADMIN, USER_A, USER_B, disposable_pg, requires_pg  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    for ctx in disposable_pg(monkeypatch, write_tables=(), migrations=("0001", "0002", "0003"),
                             extra_sql=(DDL_PATH.read_text(encoding="utf-8"),)):
        yield ctx.db


def org(db, status="pending", **cols) -> str:
    cols = {"name": "합성 기업", "status": status, "created_by_user_id": USER_A, **cols}
    if status == "active":
        cols.setdefault("verified_at", "2026-11-11T00:00:00Z")
    if status == "closed":
        cols.setdefault("closed_at", "2026-11-11T00:00:00Z")
    keys = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return db.execute(f"INSERT INTO career.organizations ({keys}) VALUES ({marks}) RETURNING organization_id",
                      tuple(cols.values())).fetchone()[0]


def invite(db, organization_id, email="new@example.invalid", seed=None, **cols):
    cols = {"organization_id": organization_id, "email_canonical": email, "token_hash": token_hash(seed or uuid4().hex),
            "invited_by_user_id": USER_A, "expires_at": "2026-11-12T00:00:00Z",
            "created_at": "2026-11-11T00:00:00Z", **cols}
    keys = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return db.execute(f"INSERT INTO career.organization_invitations ({keys}) VALUES ({marks}) RETURNING invitation_id",
                      tuple(cols.values())).fetchone()[0]


def rejects(db, statement, *args, error=psycopg.errors.CheckViolation):
    with pytest.raises(error):
        with db.transaction():
            db.execute(statement, args)


@requires_pg
def test_organization_status_and_verification_constraints(db):
    org(db, "pending")
    org(db, "active")
    rejects(db, "INSERT INTO career.organizations (name, status) VALUES ('x', 'approved')")
    rejects(db, "INSERT INTO career.organizations (name, status) VALUES ('x', 'active')")  # verified_at 없음
    rejects(db, "INSERT INTO career.organizations (name, status) VALUES ('x', 'closed')")  # closed_at 없음
    rejects(db, "INSERT INTO career.organizations (name) VALUES ('   ')")


@requires_pg
def test_membership_roles_uniqueness_and_multi_membership(db):
    first, second = org(db), org(db)
    db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'owner')",
               (first, USER_A))
    db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'member')",
               (second, USER_A))   # 다른 조직 다중 소속 허용
    rejects(db, "INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'member')",
            first, USER_A, error=psycopg.errors.UniqueViolation)
    rejects(db, "INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'admin')",
            first, USER_B)


@requires_pg
def test_invitation_ttl_is_capped_at_seven_days(db):
    o = org(db)
    invite(db, o, expires_at="2026-11-18T00:00:00Z")            # 정확히 7일 허용
    rejects(db, "INSERT INTO career.organization_invitations (organization_id, email_canonical, token_hash, created_at,"
                " expires_at) VALUES (%s, 'b@example.invalid', %s, '2026-11-11T00:00:00Z', '2026-11-18T00:00:01Z')",
            o, token_hash("ttl-over"))
    rejects(db, "INSERT INTO career.organization_invitations (organization_id, email_canonical, token_hash, created_at,"
                " expires_at) VALUES (%s, 'c@example.invalid', %s, '2026-11-11T00:00:00Z', '2026-11-11T00:00:00Z')",
            o, token_hash("ttl-zero"))


@requires_pg
def test_one_pending_invitation_per_org_and_email_but_history_allowed(db):
    o, other = org(db), org(db)
    first = invite(db, o, seed="a")
    rejects(db, "INSERT INTO career.organization_invitations (organization_id, email_canonical, token_hash, created_at,"
                " expires_at) VALUES (%s, 'new@example.invalid', %s, '2026-11-11T00:00:00Z', '2026-11-12T00:00:00Z')",
            o, token_hash("dup"), error=psycopg.errors.UniqueViolation)
    invite(db, other, seed="b")                                   # 다른 조직은 별개
    db.execute("UPDATE career.organization_invitations SET status='revoked', closed_at=now() WHERE invitation_id=%s",
               (first,))
    invite(db, o, seed="c")                                       # 종료된 초대 뒤 새 초대 허용


@requires_pg
def test_invitation_token_hash_format_uniqueness_and_email_canonical(db):
    o = org(db)
    invite(db, o, seed="same")
    rejects(db, "INSERT INTO career.organization_invitations (organization_id, email_canonical, token_hash, created_at,"
                " expires_at) VALUES (%s, 'z@example.invalid', %s, '2026-11-11T00:00:00Z', '2026-11-12T00:00:00Z')",
            o, token_hash("same"), error=psycopg.errors.UniqueViolation)
    for bad_email, bad_hash in [("Upper@Example.invalid", token_hash("u")), ("no-at-sign", token_hash("n")),
                                ("ok@example.invalid", "raw-token-not-a-hash")]:
        rejects(db, "INSERT INTO career.organization_invitations (organization_id, email_canonical, token_hash,"
                    " created_at, expires_at) VALUES (%s, %s, %s, '2026-11-11T00:00:00Z', '2026-11-12T00:00:00Z')",
                o, bad_email, bad_hash)


@requires_pg
def test_invitation_terminal_state_requires_closed_at(db):
    o = org(db)
    inv = invite(db, o)
    rejects(db, "UPDATE career.organization_invitations SET status='accepted' WHERE invitation_id=%s", inv)
    rejects(db, "UPDATE career.organization_invitations SET closed_at=now() WHERE invitation_id=%s", inv)
    db.execute("UPDATE career.organization_invitations SET status='accepted', accepted_by_user_id=%s, closed_at=now()"
               " WHERE invitation_id=%s", (USER_B, inv))
    rejects(db, "UPDATE career.organization_invitations SET resend_count=6 WHERE invitation_id=%s", inv)


@requires_pg
def test_user_deletion_cascades_membership_and_nulls_actor_references(db):
    o = org(db, created_by_user_id=USER_B)
    db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'owner')",
               (o, USER_B))
    inv = invite(db, o, invited_by_user_id=USER_B)
    db.execute("DELETE FROM career.users WHERE user_id=%s", (USER_B,))
    assert db.execute("SELECT count(*) FROM career.organization_members WHERE user_id=%s", (USER_B,)).fetchone()[0] == 0
    assert db.execute("SELECT created_by_user_id FROM career.organizations WHERE organization_id=%s",
                      (o,)).fetchone()[0] is None
    assert db.execute("SELECT invited_by_user_id FROM career.organization_invitations WHERE invitation_id=%s",
                      (inv,)).fetchone()[0] is None
    # 조직은 남는다 → 소유자 없는 조직 처리는 서비스 규칙(T122 §4, T123)
    assert db.execute("SELECT count(*) FROM career.organizations WHERE organization_id=%s", (o,)).fetchone()[0] == 1


@requires_pg
def test_organization_deletion_cascades_members_and_invitations(db):
    o = org(db)
    db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'owner')",
               (o, USER_A))
    invite(db, o)
    db.execute("DELETE FROM career.organizations WHERE organization_id=%s", (o,))
    for table in ("organization_members", "organization_invitations"):
        assert db.execute(f"SELECT count(*) FROM career.{table}").fetchone()[0] == 0


@requires_pg
def test_linked_company_is_optional_unique_while_open_and_set_null_on_delete(db):
    company = db.execute("SELECT company_id FROM career.companies LIMIT 1").fetchone()
    if company is None:
        source = db.execute("SELECT source_id FROM career.data_sources LIMIT 1").fetchone()[0]
        company = db.execute("INSERT INTO career.companies (name, source_id) VALUES ('합성 회사', %s) RETURNING company_id",
                             (source,)).fetchone()
    company_id = company[0]
    first = org(db, linked_company_id=company_id)
    rejects(db, "INSERT INTO career.organizations (name, linked_company_id) VALUES ('다른 조직', %s)", company_id,
            error=psycopg.errors.UniqueViolation)
    db.execute("UPDATE career.organizations SET status='rejected' WHERE organization_id=%s", (first,))
    org(db, linked_company_id=company_id)                         # 반려된 조직은 연결 독점 안 함
    db.execute("DELETE FROM career.job_postings WHERE company_id=%s", (company_id,))
    db.execute("DELETE FROM career.companies WHERE company_id=%s", (company_id,))
    assert db.execute("SELECT count(*) FROM career.organizations WHERE linked_company_id IS NULL").fetchone()[0] == 2


@requires_pg
def test_global_roles_are_untouched(db):
    codes = [r[0] for r in db.execute("SELECT code FROM career.roles ORDER BY code")]
    assert codes == ["admin", "job_seeker"]
    assert ADMIN  # 기존 관리자 시드 사용자는 그대로
