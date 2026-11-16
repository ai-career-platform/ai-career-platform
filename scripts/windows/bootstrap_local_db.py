"""Idempotent bootstrap of the crawler roles/schema in the LOCAL training PostgreSQL.

    .venv\\Scripts\\python.exe scripts\\windows\\bootstrap_local_db.py

Uses the admin credentials from the root .env ``*_LOCAL`` keys (see local_db_config.py) only for
role/database setup. Generates new random passwords for the crawler roles and stores them ONLY in
the ACL-restricted pgpass file (``PGPASSFILE``, outside the repository). Nothing secret is printed.

Roles (mirrors .github/workflows/crawler-mvp.yml):
  crawler_student  owner of ai_career_crawler_training; applies the repo DDL. Not used at runtime.
  crawler_staging  receives the per-table DML grants written in crawler/storage/migrations.
  crawler_local    crawler runtime login: inherits crawler_staging privileges only (no SET ROLE,
                   no DDL, no DELETE, no access to other databases).
Schema: crawler/storage/local_training_schema.sql + migrations 0002-0012 (all IF NOT EXISTS /
ON CONFLICT DO NOTHING, so re-running never recreates or drops existing objects).
"""
import json
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path

from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_db_config import REPO_ROOT, TRAINING_DB, load_local_admin  # noqa: E402

ROLES = ('crawler_student', 'crawler_staging', 'crawler_local')
PGPASS_HOSTS = ('127.0.0.1', 'localhost', 'db')  # 'db' is the hostname the staging-mode tests use
PG_BIN = Path(os.environ.get('AICP_PG_BIN', r'C:\dev\tools\pgsql18\bin'))


def new_secret():
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(32))


def restrict(path):
    user = os.environ['USERNAME']
    subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'{user}:F', 'SYSTEM:F'],
                   check=True, capture_output=True)


def ensure_pgpass(port):
    path = Path(os.environ.get('PGPASSFILE') or r'C:\dev\crawler-data\secrets\pgpass.conf')
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding='ascii').splitlines() if path.exists() else []
    keep, known = [], {}
    for line in lines:
        parts = line.split(':', 4)
        if len(parts) == 5 and parts[1] == str(port):
            if parts[3] in ROLES:
                known.setdefault(parts[3], parts[4])
            continue  # rewritten below; stale admin lines for this port are dropped on purpose
        keep.append(line)
    passwords = {role: known.get(role) or new_secret() for role in ROLES}
    keep += [f'{h}:{port}:*:{role}:{passwords[role]}' for role in ROLES for h in PGPASS_HOSTS]
    path.write_text('\n'.join(keep) + '\n', encoding='ascii')
    restrict(path)
    return path, passwords, sorted(set(ROLES) - set(known))


def psql_file(port, user, file):
    env = {k: v for k, v in os.environ.items() if not k.startswith('PGPASSWORD')}
    result = subprocess.run([str(PG_BIN / 'psql.exe'), '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1',
                             '-p', str(port), '-U', user, '-d', TRAINING_DB, '-f', str(file)],
                            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise SystemExit(f'psql failed for {Path(file).name}: {result.stderr.strip()[:300]}')
    return Path(file).name


def main():
    admin = load_local_admin()
    report = {}
    with admin.connect('postgres', autocommit=True) as c:
        version, addr, is_super = c.execute(
            "SELECT current_setting('server_version'), inet_server_addr()::text, "
            "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user)").fetchone()
        if not version.startswith('18.') or not addr.startswith(('127.0.0.1', '::1')) or not is_super:
            raise SystemExit('Refusing: not a local PostgreSQL 18 superuser connection')
        report.update(server_version=version, server_addr=addr)
        if not c.execute('SELECT 1 FROM pg_database WHERE datname=%s', (TRAINING_DB,)).fetchone():
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(TRAINING_DB)))
            report['database_created'] = True
        pgpass, passwords, generated = ensure_pgpass(admin.port)
        report['pgpass_new_passwords_for'] = generated
        for role in ROLES:
            if not c.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                c.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
                          .format(sql.Identifier(role)))
            c.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}')
                      .format(sql.Identifier(role), sql.Literal(passwords[role])))
        c.execute('GRANT crawler_staging TO crawler_local WITH INHERIT TRUE, SET FALSE')
        db = sql.Identifier(TRAINING_DB)
        c.execute(sql.SQL('ALTER DATABASE {} OWNER TO crawler_student').format(db))
        c.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(db))
        c.execute(sql.SQL('GRANT CONNECT, TEMPORARY ON DATABASE {} TO crawler_staging, crawler_local').format(db))
        for other in ('postgres', 'template1'):
            c.execute(sql.SQL('REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(other)))
    os.environ['PGPASSFILE'] = str(pgpass)
    applied = [psql_file(admin.port, 'crawler_student', REPO_ROOT / 'crawler/storage/local_training_schema.sql')]
    grant = Path(os.environ.get('TEMP', '.')) / 'aicp_postings_grant.sql'
    grant.write_text('GRANT USAGE ON SCHEMA crawler_training TO crawler_staging;\n'
                     'GRANT SELECT, INSERT, UPDATE ON crawler_training.postings TO crawler_staging;\n', encoding='ascii')
    try:
        applied.append(psql_file(admin.port, 'crawler_student', grant))
    finally:
        grant.unlink(missing_ok=True)
    for migration in sorted((REPO_ROOT / 'crawler/storage/migrations').glob('00*.sql')):
        applied.append(psql_file(admin.port, 'crawler_student', migration))
    report['applied'] = applied
    with admin.connect(TRAINING_DB, autocommit=True) as c:
        report['tables'] = c.execute("SELECT count(*) FROM pg_tables WHERE schemaname='crawler_training'").fetchone()[0]
        report['db_owner'] = c.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()').fetchone()[0]
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
