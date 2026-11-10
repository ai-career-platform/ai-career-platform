"""T86 실제 PostgreSQL 18 보안 시험 환경 (일회용 DB 전용, T16 가드와 같은 조건).

- T16_ISOLATED_DB_TEST=YES, loopback, DB 이름 t16_profile_test 일 때만 실행합니다. Staging·공유 DB 금지.
- 0001 Migration + 0001 Seed 를 그대로 적용하고 합성 사용자 A·B·관리자(@example.invalid)만 추가합니다.
- 앱은 최소 권한 역할로 접속: 전체 표 SELECT, 쓰기는 이 시험이 실제로 쓰는 표에만 부여. SUPERUSER 아님.
- 끝나면 스키마와 역할을 지웁니다.
"""
from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL

from app.core.config import get_settings
from app.core.security import issue_access_token
from app.main import create_app
from tests.conftest import TEST_SECRET, bearer

ROOT = Path(__file__).resolve().parents[3]
USER_A = UUID("00000000-0000-4000-8000-000000000861")
USER_B = UUID("00000000-0000-4000-8000-000000000862")
ADMIN = UUID("00000000-0000-4000-8000-000000000863")
# 앱이 실제로 쓰는 표에만 쓰기 권한 (career history·bookmarks 시험, 로그아웃)
WRITE_TABLES = ("user_experiences", "user_projects", "user_project_skills", "user_job_bookmarks")
requires_pg = pytest.mark.skipif(os.environ.get("T16_ISOLATED_DB_TEST") != "YES",
                                 reason="requires disposable loopback PostgreSQL")


class SecurityPG:
    def __init__(self, client: TestClient, admin, headers: dict[UUID, dict[str, str]], role: str):
        self.client, self.db, self.h, self.role = client, admin, headers, role

    def scalar(self, query: str, *args):
        return self.db.execute(query, args).fetchone()[0]

    def counts(self) -> dict[str, int]:
        tables = [r[0] for r in self.db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='career' ORDER BY tablename").fetchall()]
        return {t: self.scalar(f'SELECT count(*) FROM career."{t}"') for t in tables}


@pytest.fixture
def sec_pg(monkeypatch):
    options = conninfo_to_dict(os.environ["T16_TEST_ADMIN_URL"])
    if options.get("host") not in {"127.0.0.1", "localhost"} or options.get("dbname") != "t16_profile_test":
        pytest.fail("Only loopback disposable t16_profile_test is allowed")
    role, password = "t86_" + uuid4().hex, secrets.token_urlsafe(24)
    ident = sql.Identifier(role)
    with psycopg.connect(os.environ["T16_TEST_ADMIN_URL"], autocommit=True) as admin:
        assert 180000 <= admin.info.server_version < 190000
        admin.execute("DROP SCHEMA IF EXISTS career CASCADE")
        admin.execute("CREATE SCHEMA career")
        admin.execute((ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8"))
        admin.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
            ident, sql.Literal(password)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA career TO {}").format(ident))
        admin.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA career TO {}").format(ident))
        for table in WRITE_TABLES:
            admin.execute(sql.SQL("GRANT INSERT, UPDATE, DELETE ON career.{} TO {}").format(sql.Identifier(table), ident))
        admin.execute(sql.SQL("GRANT UPDATE ON career.auth_sessions TO {}").format(ident))
        headers = {}
        for uid, email, role_code in [(USER_A, "t86-a@example.invalid", "job_seeker"),
                                      (USER_B, "t86-b@example.invalid", "job_seeker"),
                                      (ADMIN, "t86-admin@example.invalid", "admin")]:
            admin.execute("INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)",
                          (uid, email, email, "합성 사용자"))
            admin.execute("INSERT INTO career.user_roles(user_id, role_id) SELECT %s, role_id FROM career.roles WHERE code=%s",
                          (uid, role_code))
            sid = uuid4()
            admin.execute("INSERT INTO career.auth_sessions(session_id,user_id,refresh_token_hash,expires_at) VALUES(%s,%s,%s,%s)",
                          (sid, uid, uid.hex * 2, datetime.now(UTC) + timedelta(hours=1)))
            headers[uid] = bearer(issue_access_token(TEST_SECRET, uid, sid, [], 3600))
        url = URL.create("postgresql", username=role, password=password, host=options["host"],
                         port=int(options.get("port", 5432)), database=options["dbname"])
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            with TestClient(create_app(), base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"},
                            raise_server_exceptions=False) as client:
                yield SecurityPG(client, admin, headers, role)
        finally:
            get_settings.cache_clear()
            admin.execute("DROP SCHEMA career CASCADE")
            admin.execute(sql.SQL("DROP OWNED BY {}").format(ident))
            admin.execute(sql.SQL("DROP ROLE {}").format(ident))
