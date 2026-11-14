#!/usr/bin/env python3
"""Full-system E2E harness (TEST ONLY — synthetic data, disposable loopback PostgreSQL).

한 번 실행으로:
  1. 일회용 DB `e2e_full_system` 를 새로 만든다(loopback + E2E_ALLOW_RESET=YES 일 때만).
  2. DRAFT_00(역할·스키마) + DRAFT_01(원장) → **database/migrate.py 러너**(subprocess, --target ci/local)로
     0001~최신 migration 적용 → verify/status 기록. (워크플로 YAML 에서 러너를 부르지 않는다: T115 G7)
  3. 0001 seed + tests/e2e_full/fixtures_e2e_only.sql(시험 전용 fixture) 적용.
  4. 최소 권한 로그인 역할(career_app 의 구성원)로 FastAPI(uvicorn)를 띄운다. 기능 플래그는 **이 프로세스 env 에서만** 켠다.
  5. 합성 계정(회원가입 API) 생성, 관리자 역할 부여(SQL, fixture).
  6. API 시나리오(httpx) → 브라우저 시나리오(Playwright Chromium, frontend/e2e/full-system.mjs) → SQL 정합성 검사.
  7. out 디렉터리에 results.json / summary.md / api.log / migrate.log / network·console·trace·screenshot 을 남긴다.

외부 호출 없음: Google 로그인 꺼짐, 메일은 공급자 없음(UnavailableMailSender), GCP·Cloud SQL·운영 데이터 사용 안 함.

  python tests/e2e_full/run_full_e2e.py --admin-url postgresql://user:pw@127.0.0.1:5432/postgres --out e2e-out \
      [--psql psql] [--web-dist frontend/dist] [--skip-browser]
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
HERE = Path(__file__).resolve().parent
DB_NAME = "e2e_full_system"
APP_ROLE = "e2e_full_app"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PASSWORD = "e2e-synthetic-Password-1!"

# 이 E2E 프로세스에서만 켜는 서버 기능 플래그(기본값·.env.example·Dockerfile·배포 파일은 그대로 꺼짐)
SERVER_FLAGS = {
    "JOB_APPLICATIONS_API": "true", "NOTIFICATIONS_API": "true", "COMPANY_ACCOUNTS_API": "true",
    "COMPANY_POSTINGS_API": "true", "PUBLIC_PORTFOLIO_API": "true", "PERSONAL_DATA_REQUESTS_API": "true",
    "ADMIN_MODERATION_API": "true",
}

ACCOUNTS = {  # 합성 계정. 이메일 도메인은 예약 도메인(example.invalid)
    "seeker": ("e2e-seeker@example.invalid", "E2E 구직자 A"),
    "seeker_b": ("e2e-seeker-b@example.invalid", "E2E 구직자 B"),
    "company": ("e2e-company-owner@example.invalid", "E2E 기업 담당자"),
    "outsider": ("e2e-outsider@example.invalid", "E2E 비멤버"),
    "admin": ("e2e-admin@example.invalid", "E2E 관리자"),
    "admin2": ("e2e-admin-2@example.invalid", "E2E 관리자 2"),
}


class Recorder:
    def __init__(self, out: Path):
        self.out, self.rows, self.meta = out, [], {}

    def add(self, area: str, scenario: str, step: str, status: str, evidence=None, **extra):
        row = {"area": area, "scenario": scenario, "step": step, "status": status, "source": "harness"}
        if evidence is not None:
            row["evidence"] = evidence
        row.update(extra)
        self.rows.append(row)
        print(f"[{status}] {area} / {scenario} / {step}" + (f" :: {evidence}" if status != "PASS" and evidence else ""),
              flush=True)
        return row

    def check(self, area, scenario, step, fn):
        try:
            evidence = fn()
            return self.add(area, scenario, step, "PASS", evidence)
        except AssertionError as exc:
            return self.add(area, scenario, step, "FAIL", str(exc)[:600])
        except Exception as exc:  # noqa: BLE001 — 시험 실패를 기록하고 계속
            return self.add(area, scenario, step, "FAIL", f"{type(exc).__name__}: {str(exc)[:500]}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def db_url(admin_url: str, dbname: str, **over) -> str:
    return make_conninfo(admin_url, dbname=dbname, **over)


def as_uri(conninfo: str) -> str:
    """psycopg conninfo → postgresql:// URI (DATABASE_URL·psql -d 용)."""
    from urllib.parse import quote
    d = conninfo_to_dict(conninfo)
    auth = quote(d.get("user", ""), safe="")
    if d.get("password"):
        auth += ":" + quote(d["password"], safe="")
    host = d.get("host", "127.0.0.1")
    return f"postgresql://{auth}@{host}:{d.get('port', 5432)}/{d['dbname']}"


# ---------------------------------------------------------------------------------------------- DB
def prepare_database(rec: Recorder, admin_url: str, psql: str, out: Path) -> str:
    opts = conninfo_to_dict(admin_url)
    if opts.get("host", "localhost") not in LOOPBACK:
        raise SystemExit("refusing: admin URL must be loopback (disposable PostgreSQL only)")
    if os.environ.get("E2E_ALLOW_RESET") != "YES":
        raise SystemExit("refusing: set E2E_ALLOW_RESET=YES to recreate the disposable e2e_full_system database")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        version = admin.execute("SHOW server_version").fetchone()[0]
        rec.meta["server_version"] = version
        rec.meta["server_version_num"] = admin.info.server_version
        rec.meta["version_full"] = admin.execute("SELECT version()").fetchone()[0]
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DB_NAME)))
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(APP_ROLE)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
    target = db_url(admin_url, DB_NAME)
    with psycopg.connect(target, autocommit=True) as conn:
        for rel in ("database/security/DRAFT_00_create_roles_schema.sql", "database/security/DRAFT_01_migration_history.sql"):
            conn.execute((ROOT / rel).read_text(encoding="utf-8"))
    rec.add("PLATFORM", "db", "disposable database created", "PASS",
            {"database": DB_NAME, "server_version": version})

    # migration 러너(subprocess). CI 에서는 --target ci, 로컬은 local.
    target_env = "ci" if os.environ.get("CI") else "local"
    env = dict(os.environ, MIGRATE_PSQL=f'"{psql}" -d "{as_uri(target)}"')  # shlex(posix) 로 나뉨
    log = []
    for args in (["lint"], ["apply", "--target", target_env], ["verify"], ["status"]):
        res = subprocess.run([sys.executable, "-B", str(ROOT / "database/migrate.py"), *args], env=env,
                             capture_output=True, text=True, encoding="utf-8")
        log.append(f"$ migrate.py {' '.join(args)}  (exit {res.returncode})\n{res.stdout}{res.stderr}")
        if res.returncode != 0:
            (out / "migrate.log").write_text("\n".join(log), encoding="utf-8")
            rec.add("PLATFORM", "migrations", f"migrate.py {args[0]}", "FAIL", (res.stdout + res.stderr)[-800:])
            raise SystemExit("migration runner failed")
    (out / "migrate.log").write_text("\n".join(log), encoding="utf-8")
    with psycopg.connect(target, autocommit=True) as conn:
        applied = [r[0] for r in conn.execute(
            "SELECT version FROM career_migration.schema_migrations ORDER BY version").fetchall()]
    files = sorted(p.name[:4] for p in (ROOT / "database/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    rec.meta["migrations_applied"] = applied
    status = "PASS" if applied == files else "FAIL"
    rec.add("PLATFORM", "migrations", "runner applied every migration file in order (lint/apply/verify/status)",
            status, {"applied": applied, "files": files, "target_env": target_env})

    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        conn.execute((HERE / "fixtures_e2e_only.sql").read_text(encoding="utf-8"))
        app_password = secrets.token_urlsafe(24)
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE IN ROLE career_app")
                     .format(sql.Identifier(APP_ROLE), sql.Literal(app_password)))
        counts = conn.execute("SELECT (SELECT count(*) FROM career.job_postings), (SELECT count(*) FROM career.users), "
                              "(SELECT count(*) FROM career.consent_policies)").fetchone()
    rec.add("PLATFORM", "seed", "0001 seed + test-only fixtures applied", "PASS",
            {"job_postings": counts[0], "users": counts[1], "consent_policies": counts[2]})
    return as_uri(db_url(admin_url, DB_NAME, user=APP_ROLE, password=app_password))


# ---------------------------------------------------------------------------------------------- 프로세스
def wait_http(url: str, proc: subprocess.Popen, seconds: float = 60) -> None:
    import httpx
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early ({proc.returncode}) for {url}")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"timeout waiting for {url}")


def backend_env(database_url: str, storage: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "DATABASE_URL"))}
    env.update(SERVER_FLAGS)
    env.update({
        "APP_ENV": "test", "DATABASE_URL": database_url, "JWT_SECRET": secrets.token_urlsafe(48),
        "AUTH_COOKIE_SECURE": "false", "DOCUMENT_STORAGE_ROOT": str(storage), "GOOGLE_LOGIN_ENABLED": "false",
        "SIGNUP_IP_MAX_ATTEMPTS": "1000", "LOGIN_IP_MAX_ATTEMPTS": "1000", "LOGIN_MAX_FAILURES": "100",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def start_api(env: dict, port: int, out: Path) -> subprocess.Popen:
    log = (out / "api.log").open("wb")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    wait_http(f"http://127.0.0.1:{port}/health/db", proc)
    return proc


def start_web(api_port: int, web_port: int, out: Path) -> subprocess.Popen:
    """vite preview(빌드된 dist) — /api 는 vite 설정의 proxy(DEV_API_PROXY_TARGET)로 API 에 전달(같은 Origin)."""
    env = dict(os.environ, DEV_API_PROXY_TARGET=f"http://127.0.0.1:{api_port}")
    log = (out / "web.log").open("wb")
    vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    proc = subprocess.Popen(["node", str(vite), "preview", "--port", str(web_port), "--strictPort", "--host", "127.0.0.1"],
                            cwd=FRONTEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    wait_http(f"http://127.0.0.1:{web_port}/", proc)
    return proc


def stop(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------------------------- 계정
def create_accounts(rec: Recorder, api: str, admin_url: str) -> dict:
    import httpx
    from tests_e2e_api import signup  # noqa: E402 (같은 폴더 모듈)
    ids = {}
    with httpx.Client(base_url=api, timeout=30) as client:
        for key, (email, name) in ACCOUNTS.items():
            ids[key] = signup(client, email, PASSWORD, name)
    with psycopg.connect(db_url(admin_url, DB_NAME), autocommit=True) as conn:
        for key in ("admin", "admin2"):
            conn.execute("INSERT INTO career.user_roles (user_id, role_id) SELECT %s, role_id FROM career.roles "
                         "WHERE code = 'admin'", (ids[key]["user_id"],))
    rec.add("PLATFORM", "accounts", "synthetic accounts via real signup API + admin role fixture", "PASS",
            {k: v["email"] for k, v in ids.items()})
    return ids


# ---------------------------------------------------------------------------------------------- 브라우저
def run_browser(rec: Recorder, web: str, env: dict, accounts: dict, out: Path, state: dict) -> list[dict]:
    script = FRONTEND / "e2e" / "full-system.mjs"
    result_file = out / "browser-results.json"
    state_file = out / "harness-state.json"
    state_file.write_text(json.dumps(state, default=str), encoding="utf-8")
    node_env = dict(env, E2E_BASE_URL=web, E2E_OUT=str(result_file), E2E_ARTIFACTS=str(out / "browser"),
                    E2E_PASSWORD=PASSWORD, E2E_STATE=str(state_file), E2E_PYTHON=sys.executable,
                    E2E_BACKEND_DIR=str(BACKEND),
                    E2E_HELPERS=str(HERE / "e2e_helpers.py"), E2E_ACCOUNTS=json.dumps(accounts))
    res = subprocess.run(["node", str(script)], cwd=FRONTEND, env=node_env, capture_output=True, text=True,
                         encoding="utf-8", timeout=1800)
    (out / "browser-stdout.log").write_text(res.stdout + "\n--- stderr ---\n" + res.stderr, encoding="utf-8")
    if not result_file.exists():
        rec.add("PLATFORM", "browser", "Playwright script produced results", "FAIL", (res.stderr or res.stdout)[-800:])
        return []
    data = json.loads(result_file.read_text(encoding="utf-8"))
    rec.meta["browser"] = data.get("browser")
    return data.get("results", [])


# ---------------------------------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--admin-url", default=os.environ.get("E2E_ADMIN_URL"), required=False)
    parser.add_argument("--psql", default=os.environ.get("E2E_PSQL", "psql"))
    parser.add_argument("--out", default="e2e-out")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--web-port", type=int, default=0)
    args = parser.parse_args()
    if not args.admin_url:
        raise SystemExit("--admin-url (or E2E_ADMIN_URL) is required")
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "browser").mkdir(parents=True)
    storage = out / "_runtime" / "documents"
    storage.parent.mkdir(parents=True)
    rec = Recorder(out)
    rec.meta.update(started_at=datetime.now(UTC).isoformat(), git_sha=os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        server_flags=SERVER_FLAGS)
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(BACKEND))
    api_proc = web_proc = None
    exit_code = 1
    try:
        database_url = prepare_database(rec, args.admin_url, args.psql, out)
        env = backend_env(database_url, storage)
        api_port = args.api_port or free_port()
        api_proc = start_api(env, api_port, out)
        api = f"http://127.0.0.1:{api_port}"
        rec.add("PLATFORM", "api", "uvicorn FastAPI started with E2E-only flags", "PASS", {"port": api_port})
        accounts = create_accounts(rec, api, args.admin_url)

        import tests_e2e_api as api_checks
        import tests_e2e_db as db_checks
        admin_db = db_url(args.admin_url, DB_NAME)
        state = api_checks.run(rec, api, accounts, PASSWORD, admin_db, env)

        browser_rows = []
        if args.skip_browser:
            rec.add("PLATFORM", "browser", "Playwright browser scenarios", "NOT_RUN", "--skip-browser")
        else:
            web_port = args.web_port or free_port()
            web_proc = start_web(api_port, web_port, out)
            rec.add("PLATFORM", "web", "vite preview serving the built React app (proxy /api → API)", "PASS",
                    {"port": web_port})
            browser_rows = run_browser(rec, f"http://127.0.0.1:{web_port}", env, accounts, out, state)
            browser_state = out / "browser-state.json"
            if browser_state.exists():
                state["browser"] = json.loads(browser_state.read_text(encoding="utf-8"))
        db_checks.run(rec, admin_db, accounts, state)
        rec.rows.extend(browser_rows)
        exit_code = 0 if not any(r["status"] == "FAIL" for r in rec.rows) else 1
    except SystemExit as exc:
        rec.add("PLATFORM", "harness", "harness aborted", "FAIL", str(exc))
    except Exception as exc:  # noqa: BLE001
        rec.add("PLATFORM", "harness", "harness crashed", "FAIL", traceback.format_exc()[-1500:])
    finally:
        stop(web_proc)
        stop(api_proc)
        shutil.rmtree(out / "_runtime", ignore_errors=True)
        write_reports(rec, out)
    return exit_code


def write_reports(rec: Recorder, out: Path) -> None:
    summary: dict[str, int] = {}
    for r in rec.rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    rec.meta["finished_at"] = datetime.now(UTC).isoformat()
    (out / "results.json").write_text(json.dumps({"meta": rec.meta, "summary": summary, "results": rec.rows},
                                                 ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# Full-system E2E results", "", f"- server_version: {rec.meta.get('server_version')}",
             f"- git_sha: {rec.meta.get('git_sha')}", f"- migrations: {rec.meta.get('migrations_applied')}",
             f"- browser: {rec.meta.get('browser')}", f"- summary: {summary}", "",
             "| area | scenario | step | status | source | evidence |", "|---|---|---|---|---|---|"]
    for r in rec.rows:
        ev = json.dumps(r.get("evidence", r.get("error", r.get("reason", ""))), ensure_ascii=False, default=str)
        lines.append(f"| {r['area']} | {r['scenario']} | {r['step']} | {r['status']} | {r.get('source', '')} | "
                     f"{ev[:300].replace('|', '/')} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
