"""#328 로컬 E2E 용 **일회용** PostgreSQL 준비. 지정한 DB 의 `career` 스키마를 지우고 다시 만든다(운영·Staging 금지).

    python scripts/e2e/google_sso/setup_db.py postgresql://user@127.0.0.1:55433/e2e_google
    python scripts/e2e/google_sso/setup_db.py <url> --report     # 시험 뒤 Google 관련 행 요약(이메일·sub 원문 없음)
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

REPO = pathlib.Path(__file__).resolve().parents[3]
MIGRATIONS = sorted((REPO / "database" / "migrations").glob("000*_*.sql"))
SEED = REPO / "database" / "seeds" / "0001_initial_seed.sql"
POLICIES = [("terms", True), ("privacy", True), ("llm_processing", False)]


def reset(engine) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA career")
        for sql in (*MIGRATIONS, SEED):
            conn.exec_driver_sql(sql.read_text(encoding="utf-8").replace("%", "%%"))
        for code, required in POLICIES:
            conn.execute(text(
                "INSERT INTO career.consent_policies (policy_code, version, is_required, content_url, effective_at) "
                "VALUES (:c, '2026-11', :r, :u, '2026-11-06T00:00:00Z')"),
                {"c": code, "r": required, "u": f"https://docs.ai-career.invalid/{code}/2026-11"})


def report(engine) -> None:
    queries = {
        "users_total": "SELECT count(*) FROM career.users",
        "google_identities": "SELECT count(*) FROM career.auth_identities WHERE provider = 'google'",
        "google_identities_with_password": "SELECT count(*) FROM career.auth_identities WHERE provider='google' AND password_hash IS NOT NULL",
        "local_identities_e2e": "SELECT count(*) FROM career.auth_identities i JOIN career.users u USING (user_id) "
                                "WHERE i.provider='local' AND u.email LIKE '%@e2e.example.com'",
        "google_users_roles": "SELECT string_agg(DISTINCT r.code, ',') FROM career.auth_identities i "
                              "JOIN career.user_roles ur USING (user_id) JOIN career.roles r USING (role_id) WHERE i.provider='google'",
        "google_users_consents": "SELECT count(*) FROM career.user_consents c JOIN career.auth_identities i USING (user_id) "
                                 "WHERE i.provider='google'",
        "google_users_sessions": "SELECT count(*) FROM career.auth_sessions s JOIN career.auth_identities i USING (user_id) "
                                 "WHERE i.provider='google'",
        "google_users_revoked_sessions": "SELECT count(*) FROM career.auth_sessions s JOIN career.auth_identities i USING (user_id) "
                                         "WHERE i.provider='google' AND s.revoked_at IS NOT NULL",
        "duplicate_google_subjects": "SELECT count(*) FROM (SELECT subject FROM career.auth_identities WHERE provider='google' "
                                     "GROUP BY subject HAVING count(*) > 1) d",
        "conflict_email_identities": "SELECT count(*) FROM career.auth_identities i JOIN career.users u USING (user_id) "
                                     "WHERE u.email_canonical = 'local.user@e2e.example.com'",
    }
    with engine.connect() as conn:
        for name, sql in queries.items():
            print(f"{name}={conn.execute(text(sql)).scalar()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    host = urlsplit(args.url).hostname
    if host not in {"127.0.0.1", "localhost"}:
        print("refusing: only a loopback disposable database is allowed", file=sys.stderr)
        return 2
    engine = create_engine(args.url.replace("postgresql://", "postgresql+psycopg://", 1))
    report(engine) if args.report else reset(engine)
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
