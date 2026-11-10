"""T88 API/DB/AI(Mock) 성능 기준선 측정 — 일회용 로컬 PostgreSQL 전용.

    T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/t16_profile_test \
      python perf/t88_baseline.py [--duration 3] [--levels 1,4,8,16] [--overload 32] [--out result.json]

- T16 가드와 같은 조건(loopback, DB 이름 t16_profile_test, 환경 플래그)이 아니면 실행을 거부합니다. Staging·공유 DB 금지.
- 0001~0003 Migration + Seed 위에 **합성 데이터**만 만듭니다(기업·공고·감사·사용량·문서). 실제 사용자 데이터 없음.
- 실제 uvicorn 서버(단일 worker, 배포 Dockerfile 과 같은 기본값)를 같은 프로세스의 스레드로 띄우고, 표준 라이브러리
  스레드 + HTTP keep-alive 로 단계적 동시성 부하를 줍니다. 새 의존성 없음.
- 측정: 요청 수·성공률·오류율·p50/p95/p99·처리량, 프로세스 CPU·메모리, DB 풀 사용 최대치, SQL 실행 지연, timeout 수.
- AI 는 **Mock 분석 worker**(MockAnalysisProvider)만 측정합니다. 실제 모델 추론 성능이 아닙니다.
- 합격 기준은 정하지 않습니다(PM 미승인). 결과는 기준선으로만 기록합니다.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import json
import os
import platform
import secrets
import statistics
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

PERF_USER = UUID("00000000-0000-4000-8000-000000000881")
PERF_ADMIN = UUID("00000000-0000-4000-8000-000000000882")
SECRET = "t88-perf-secret-0123456789-abcdefghij"
AI_USERS = [UUID(int=0x8800 + i) for i in range(10)]   # 분석 요청은 사용자당 요청 한도가 있어 10명으로 나눔
DOCS_PER_AI_USER = 5


# ---------------------------------------------------------------- pure helpers (unit-tested)
def percentile(values: list[float], pct: float) -> float | None:
    """nearest-rank 백분위수(ms). 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(round(pct / 100 * len(ordered) + 0.4999)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize(latencies_ms: list[float], statuses: list[int], timeouts: int, wall_s: float) -> dict:
    total = len(statuses) + timeouts
    ok = sum(1 for s in statuses if 200 <= s < 400)
    return {
        "requests": total, "success": ok,
        "success_rate": round(ok / total, 4) if total else None,
        "error_rate": round((total - ok) / total, 4) if total else None,
        "status_counts": {str(s): statuses.count(s) for s in sorted(set(statuses))},
        "timeouts": timeouts,
        "p50_ms": _r(percentile(latencies_ms, 50)), "p95_ms": _r(percentile(latencies_ms, 95)),
        "p99_ms": _r(percentile(latencies_ms, 99)), "max_ms": _r(max(latencies_ms) if latencies_ms else None),
        "throughput_rps": round(total / wall_s, 1) if wall_s else None,
    }


def _r(value):
    return None if value is None else round(value, 2)


def guard(url: str) -> None:
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(url)
    if os.environ.get("T16_ISOLATED_DB_TEST") != "YES":
        raise SystemExit("refused: T16_ISOLATED_DB_TEST=YES is required (disposable DB only)")
    if options.get("host") not in {"127.0.0.1", "localhost"} or options.get("dbname") != "t16_profile_test":
        raise SystemExit("refused: only loopback disposable t16_profile_test is allowed")


# ---------------------------------------------------------------- process metrics (stdlib only)
def memory_mb() -> dict:
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p          # 64비트 의사 핸들(-1)이 잘리지 않게
        kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return {"rss_mb": None, "peak_rss_mb": None}
        return {"rss_mb": round(counters.WorkingSetSize / 2**20, 1), "peak_rss_mb": round(counters.PeakWorkingSetSize / 2**20, 1)}
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {"rss_mb": None, "peak_rss_mb": round(peak, 1)}


def environment(admin) -> dict:
    return {
        "os": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "processor": platform.processor(), "python": platform.python_version(),
        "postgresql": admin.execute("SHOW server_version").fetchone()[0],
        "total_ram_gb": _total_ram_gb(), "db_pool_size": int(os.environ.get("DB_POOL_SIZE", 5)),
        "db_timeout_s": int(os.environ.get("DB_TIMEOUT_SECONDS", 5)), "uvicorn_workers": 1,
    }


def _total_ram_gb():
    if os.name == "nt":
        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return round(status.ullTotalPhys / 2**30, 1)
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------- disposable DB with synthetic data
def build_database(admin_url: str, sizes: dict) -> tuple[str, str]:
    import psycopg
    from psycopg import sql
    role, password = "t88_" + uuid4().hex, secrets.token_urlsafe(24)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS career CASCADE")
        admin.execute("CREATE SCHEMA career")
        for path in sorted((ROOT / "database/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")):
            admin.execute(path.read_text(encoding="utf-8"))
        admin.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        source = admin.execute("SELECT source_id FROM career.data_sources WHERE code='synthetic_seed'").fetchone()[0]
        role_id = admin.execute("SELECT job_role_id FROM career.job_roles ORDER BY code LIMIT 1").fetchone()[0]
        admin.execute("""INSERT INTO career.companies (name, source_id)
                         SELECT 'T88 합성기업 ' || g, %s FROM generate_series(1, %s) g""", (source, sizes["companies"]))
        admin.execute("""INSERT INTO career.job_postings (company_id, job_role_id, source_id, title, employment_type,
                             location_text, status, published_at, expires_at)
                         SELECT c.company_id, %s, %s,
                                (ARRAY['백엔드','프론트엔드','데이터','AI','DevOps'])[1 + g %% 5] || ' 개발자 T88-' || g,
                                'full_time', '서울', 'published', now() - (g || ' minutes')::interval, now() + interval '30 days'
                         FROM generate_series(1, %s) g
                         JOIN LATERAL (SELECT company_id FROM career.companies WHERE name = 'T88 합성기업 ' || (1 + g %% %s)) c ON true""",
                      (role_id, source, sizes["postings"], sizes["companies"]))
        for uid, email, code in [(PERF_USER, "t88-user@example.invalid", "job_seeker"),
                                 (PERF_ADMIN, "t88-admin@example.invalid", "admin")]:
            admin.execute("INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)",
                          (uid, email, email, "합성 사용자"))
            admin.execute("INSERT INTO career.user_roles(user_id, role_id) SELECT %s, role_id FROM career.roles WHERE code=%s",
                          (uid, code))
        admin.execute("""INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, request_id, occurred_at)
                         SELECT %s, 'system.synthetic.event', 'synthetic', 'req-t88-' || g,
                                now() - (g || ' seconds')::interval FROM generate_series(1, %s) g""",
                      (PERF_ADMIN, sizes["audit_events"]))
        admin.execute("""INSERT INTO career.ai_usage_records (user_id, provider_model, feature_code, input_tokens,
                             output_tokens, estimated_cost_usd, occurred_at)
                         SELECT NULL, 'mock-model-' || (g %% 3), (ARRAY['document_analysis','rag_answer','agent'])[1 + g %% 3],
                                100 + g %% 50, 20 + g %% 10, 0.000100, now() - (g || ' minutes')::interval
                         FROM generate_series(1, %s) g""", (sizes["usage_records"],))
        admin.execute("INSERT INTO career.consent_policies(policy_code,version,is_required,content_url,effective_at) "
                      "VALUES('llm_processing','v1',false,'https://example.invalid/llm', now() - interval '1 day')")
        for uid in AI_USERS:
            email = f"t88-ai-{uid.hex[-4:]}@example.invalid"
            admin.execute("INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)",
                          (uid, email, email, "합성 사용자"))
            admin.execute("INSERT INTO career.user_roles(user_id, role_id) SELECT %s, role_id FROM career.roles WHERE code='job_seeker'",
                          (uid,))
            admin.execute("INSERT INTO career.user_consents(user_id,policy_code,policy_version,granted) "
                          "VALUES(%s,'llm_processing','v1',true)", (uid,))
        admin.execute("ANALYZE")
        ident = sql.Identifier(role)
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
            ident, sql.Literal(password)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA career TO {}").format(ident))
        admin.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA career TO {}").format(ident))
        for table in ("user_documents", "document_analyses", "model_versions", "user_skills"):
            admin.execute(sql.SQL("GRANT INSERT, UPDATE ON career.{} TO {}").format(sql.Identifier(table), ident))
    return role, password


def explain(admin_url: str) -> dict:
    """대표 쿼리의 실행 계획(인덱스 사용 여부·실행 시간). 저장소 쿼리를 단순화한 형태."""
    import psycopg
    queries = {
        "job_postings_search_ilike": "SELECT job_posting_id FROM career.job_postings WHERE status='published' "
                                     "AND title ILIKE '%백엔드%' ORDER BY published_at DESC, job_posting_id DESC LIMIT 21",
        "job_postings_latest": "SELECT job_posting_id FROM career.job_postings WHERE status='published' "
                               "ORDER BY published_at DESC, job_posting_id DESC LIMIT 21",
        "audit_keyset_page": "SELECT audit_event_id FROM career.audit_events WHERE occurred_at >= now() - interval '1 day' "
                             "AND occurred_at < now() ORDER BY occurred_at DESC, audit_event_id DESC LIMIT 51",
        "ai_usage_daily": "SELECT to_char((occurred_at AT TIME ZONE 'Asia/Seoul')::date,'YYYY-MM-DD'), count(*), "
                          "sum(input_tokens) FROM career.ai_usage_records WHERE occurred_at >= now() - interval '7 days' "
                          "GROUP BY 1 ORDER BY 1",
    }
    out = {}
    with psycopg.connect(admin_url, autocommit=True) as admin:
        for name, query in queries.items():
            plan = admin.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query).fetchone()[0][0]
            nodes = []

            def walk(node):
                nodes.append(node["Node Type"] + (f" on {node['Relation Name']}" if "Relation Name" in node else "")
                             + (f" using {node['Index Name']}" if "Index Name" in node else ""))
                for child in node.get("Plans", []):
                    walk(child)
            walk(plan["Plan"])
            out[name] = {"execution_ms": round(plan["Execution Time"], 3), "nodes": nodes}
    return out


# ---------------------------------------------------------------- load generator
class SqlTimer:
    def __init__(self, engine):
        from sqlalchemy import event
        self.samples: list[float] = []
        self.lock = threading.Lock()
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("t88_start", []).append(time.perf_counter())

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        start = conn.info["t88_start"].pop()
        with self.lock:
            self.samples.append((time.perf_counter() - start) * 1000)

    def take(self) -> list[float]:
        with self.lock:
            samples, self.samples = self.samples, []
        return samples


class PoolSampler(threading.Thread):
    def __init__(self, engine):
        super().__init__(daemon=True)
        self.engine, self.max_checked_out, self.stop_flag = engine, 0, threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            self.max_checked_out = max(self.max_checked_out, self.engine.pool.checkedout())
            time.sleep(0.005)


def run_step(port: int, method: str, path: str, headers: dict, concurrency: int, duration: float,
             sql_timer: SqlTimer, engine, client_timeout: float = 10.0) -> dict:
    latencies: list[float] = []
    statuses: list[int] = []
    timeouts = [0]
    lock = threading.Lock()
    deadline = time.monotonic() + duration
    sql_timer.take()
    sampler = PoolSampler(engine)
    sampler.start()
    cpu0, wall0 = time.process_time(), time.perf_counter()

    def worker():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=client_timeout)
        local_lat, local_st, local_to = [], [], 0
        while time.monotonic() < deadline:
            started = time.perf_counter()
            try:
                conn.request(method, path, headers=headers)
                response = conn.getresponse()
                response.read()
                local_st.append(response.status)
                local_lat.append((time.perf_counter() - started) * 1000)
            except (TimeoutError, OSError):
                local_to += 1
                conn.close()
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=client_timeout)
        conn.close()
        with lock:
            latencies.extend(local_lat)
            statuses.extend(local_st)
            timeouts[0] += local_to

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    sampler.stop_flag.set()
    sampler.join()
    sql = sql_timer.take()
    result = summarize(latencies, statuses, timeouts[0], wall)
    result.update({
        "concurrency": concurrency, "duration_s": round(wall, 2),
        "process_cpu_cores": round(cpu / wall, 2), **memory_mb(),
        "db_pool_max_checked_out": sampler.max_checked_out,
        "sql_statements": len(sql), "sql_p50_ms": _r(percentile(sql, 50)), "sql_p95_ms": _r(percentile(sql, 95)),
        "sql_p99_ms": _r(percentile(sql, 99)),
    })
    return result


def ai_mock_batch(app) -> dict:
    """Mock 분석 worker 처리 시간 (실제 AI 추론 아님): 합성 문서 n 개를 큐에 넣고 worker.run() 1 회."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.repositories.document_analyses import SqlAnalysisRepository
    from app.services.analysis_provider import MockAnalysisProvider
    from app.services.document_analyses import AnalysisWorker

    class MemoryStorage:
        def __init__(self): self.files = {}
        def put(self, key, content): self.files[key] = content
        def read(self, key): return self.files[key]
        def delete(self, key): self.files.pop(key, None)

    engine = app.state.db_session_factory.kw["bind"]
    storage = MemoryStorage()
    content = b"%PDF-1.7\nsynthetic resume Python Java SQL\n%%EOF"
    with Session(engine) as db, db.begin():
        for owner in AI_USERS:
            for _ in range(DOCS_PER_AI_USER + 1):   # +1: 요청 한도 확인용
                document_id, key = uuid4(), secrets.token_hex(32)
                storage.put(key, content)
                db.execute(text("""INSERT INTO career.user_documents (document_id, owner_user_id, kind, original_filename,
                    mime_type, size_bytes, storage_key, checksum_sha256, status) VALUES (:d, :u, 'resume', 'synthetic.pdf',
                    'application/pdf', :n, :k, :c, 'ready')"""),
                    {"d": document_id, "u": owner, "n": len(content), "k": key, "c": hashlib.sha256(content).hexdigest()})
    return {"storage": storage}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--levels", default="1,4,8,16")
    parser.add_argument("--overload", default="32")
    parser.add_argument("--postings", type=int, default=5000)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    admin_url = os.environ.get("T16_TEST_ADMIN_URL", "")
    guard(admin_url)

    import psycopg
    import uvicorn
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy import URL
    from app.core.config import get_settings
    from app.core.security import issue_access_token
    from app.main import create_app

    sizes = {"companies": 200, "postings": args.postings, "audit_events": 20000, "usage_records": 20000}
    role, password = build_database(admin_url, sizes)
    try:
        return _measure(args, admin_url, role, password, sizes)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            from psycopg import sql
            admin.execute("DROP SCHEMA IF EXISTS career CASCADE")
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _measure(args, admin_url, role, password, sizes) -> int:
    import psycopg
    import uvicorn
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy import URL
    from app.core.config import get_settings
    from app.core.security import issue_access_token
    from app.main import create_app
    options = conninfo_to_dict(admin_url)
    os.environ.update({"APP_ENV": "test", "JWT_SECRET": SECRET, "DATABASE_URL": URL.create(
        "postgresql", username=role, password=password, host=options["host"], port=int(options.get("port", 5432)),
        database=options["dbname"]).render_as_string(hide_password=False)})
    get_settings.cache_clear()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        tokens = {}
        for uid in (PERF_USER, PERF_ADMIN, *AI_USERS):
            sid = uuid4()
            admin.execute("INSERT INTO career.auth_sessions(session_id,user_id,refresh_token_hash,expires_at) VALUES(%s,%s,%s,%s)",
                          (sid, uid, uid.hex * 2, datetime.now(UTC) + timedelta(hours=2)))
            tokens[uid] = {"Authorization": "Bearer " + issue_access_token(SECRET, uid, sid, [], 3600)}
        env_info = environment(admin)

    app = create_app()
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False,
                                           lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    engine = app.state.db_session_factory.kw["bind"]
    sql_timer = SqlTimer(engine)

    window = urlencode({"from": (datetime.now(UTC) - timedelta(days=1)).isoformat(), "to": datetime.now(UTC).isoformat(), "limit": 50})
    today = datetime.now(UTC).date()
    usage = urlencode({"from": (today - timedelta(days=6)).isoformat(), "to": today.isoformat(), "group_by": "day"})
    endpoints = [
        ("health (no DB)", "GET", "/health", {}),
        ("job_postings latest", "GET", "/api/v1/job-postings?limit=20", {}),
        ("job_postings search q", "GET", "/api/v1/job-postings?" + urlencode({"q": "백엔드", "limit": 20}), {}),
        ("job_roles", "GET", "/api/v1/job-roles?limit=20", {}),
        ("me (auth+DB)", "GET", "/api/v1/me", tokens[PERF_USER]),
        ("admin audit-events", "GET", "/api/v1/admin/audit-events?" + window, tokens[PERF_ADMIN]),
        ("admin ai-usage", "GET", "/api/v1/admin/ai-usage?" + usage, tokens[PERF_ADMIN]),
    ]
    levels = [int(x) for x in args.levels.split(",") if x]
    overload = [int(x) for x in args.overload.split(",") if x]
    results = []
    for name, method, path, headers in endpoints:
        run_step(port, method, path, headers, 1, 0.5, sql_timer, engine)   # warm-up (not recorded)
        for level in levels + (overload if name in ("job_postings search q", "me (auth+DB)") else []):
            step = run_step(port, method, path, headers, level, args.duration, sql_timer, engine)
            step.update({"endpoint": name, "overload": level in overload})
            results.append(step)
            print(f"{name:24} c={level:<3} n={step['requests']:<6} ok={step['success_rate']} "
                  f"p50={step['p50_ms']} p95={step['p95_ms']} p99={step['p99_ms']} rps={step['throughput_rps']} "
                  f"pool={step['db_pool_max_checked_out']} sql_p95={step['sql_p95_ms']} to={step['timeouts']}", flush=True)

    # AI (Mock): enqueue via the real API then one worker batch
    from sqlalchemy.orm import Session
    from app.repositories.document_analyses import SqlAnalysisRepository
    from app.services.analysis_provider import MockAnalysisProvider
    from app.services.document_analyses import AnalysisWorker
    batch = ai_mock_batch(app)
    enqueue_lat, enqueue_status = [], []
    with psycopg.connect(admin_url, autocommit=True) as admin:
        for owner in AI_USERS:
            doc_ids = [r[0] for r in admin.execute("SELECT document_id FROM career.user_documents WHERE owner_user_id=%s "
                                                    "ORDER BY document_id", (owner,)).fetchall()]
            for document_id in doc_ids:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                started = time.perf_counter()
                conn.request("POST", f"/api/v1/documents/{document_id}/analyses",
                             body=json.dumps({"analysis_type": "skill_extraction"}),
                             headers={**tokens[owner], "Content-Type": "application/json"})
                response = conn.getresponse()
                response.read()
                enqueue_status.append(response.status)
                enqueue_lat.append((time.perf_counter() - started) * 1000)
                conn.close()
    accepted = enqueue_status.count(202)
    with Session(engine) as db:
        worker = AnalysisWorker(SqlAnalysisRepository(db), batch["storage"], MockAnalysisProvider())
        started, processed, runs, summaries = time.perf_counter(), 0, 0, []
        while processed < accepted and runs < 20:   # worker.run() 은 한 번에 일부(배치)만 처리
            summary = worker.run()
            summaries.append(str(summary))
            processed += summary.succeeded + summary.failed
            runs += 1
            if summary.succeeded + summary.failed == 0:
                break
        worker_s = time.perf_counter() - started
        summary = f"runs={runs} processed={processed} " + " | ".join(summaries)
    assert set(enqueue_status) <= {202, 429}, enqueue_status
    ai = {"label": "MOCK provider - not real AI inference", "accepted_jobs": accepted,
          "rate_limited_429": enqueue_status.count(429), "enqueue": summarize(enqueue_lat, enqueue_status, 0, sum(enqueue_lat) / 1000),
          "worker_batch_s": round(worker_s, 3), "worker_summary": str(summary),
          "per_job_ms": round(worker_s * 1000 / max(1, processed), 2)}
    print("AI mock:", json.dumps(ai, ensure_ascii=False), flush=True)

    server.should_exit = True
    thread.join(timeout=10)
    report = {"generated_at": datetime.now(UTC).isoformat(), "environment": env_info, "data_sizes": sizes,
              "duration_per_step_s": args.duration, "steps": results, "ai_mock": ai, "query_plans": explain(admin_url)}
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["query_plans"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
