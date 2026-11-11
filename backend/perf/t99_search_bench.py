"""T99 고급 검색 성능·실행 계획 측정 (일회용 DB 전용, 합성 데이터만).

    T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://<admin>@127.0.0.1:<port>/t16_profile_test \
        python -m perf.t99_search_bench --postings 100000 --out ../docs/search/T99_SEARCH_PERF_RESULTS.json

- T88 과 같은 가드(루프백 + t16_profile_test + T16_ISOLATED_DB_TEST=YES). 공유 Staging DB 에는 연결하지 않습니다.
- 앱의 SqlJobPostingRepository 가 만드는 SQL 을 그대로 측정합니다(같은 바인딩 값으로 EXPLAIN ANALYZE).
- 단계: (A) 0001 인덱스만 → (B) + database/proposed/T99_job_search_indexes.sql → (C) + pg_trgm 옵션.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import sqlalchemy_url
from app.repositories.job_postings import PostingFilter, SqlJobPostingRepository
from perf.t88_baseline import guard, percentile

ROOT = Path(__file__).resolve().parents[2]
LOCATIONS = ["서울 강남구", "서울 마포구", "경기 성남시 분당구", "경기도 수원시", "부산 해운대구", "대구 수성구", "인천 연수구",
             "광주 서구", "대전 유성구", "충청북도 청주시", "전북 전주시", "경남 창원시", "제주 제주시", "재택근무", None]
TITLES = ["백엔드 개발자", "프론트엔드 개발자", "데이터 엔지니어", "QA 엔지니어", "DevOps 엔지니어", "디자이너", "PM",
          "모바일 개발자", "AI 연구원", "보안 엔지니어"]


def build(admin_url: str, postings: int, companies: int) -> None:
    import psycopg
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS career CASCADE")
        admin.execute("CREATE SCHEMA career")
        admin.execute((ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8"))
        admin.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        admin.execute("TRUNCATE career.job_postings CASCADE")
        src = admin.execute("SELECT source_id FROM career.data_sources WHERE code='synthetic_seed'").fetchone()[0]
        admin.execute("INSERT INTO career.companies (name, source_id) SELECT 'T99 합성기업 ' || g, %s "
                      "FROM generate_series(1, %s) g", (src, companies))
        admin.execute(
            """WITH c AS (SELECT array_agg(company_id ORDER BY name) ids FROM career.companies WHERE name LIKE 'T99 %%'),
                    r AS (SELECT array_agg(job_role_id ORDER BY code) ids FROM career.job_roles)
               INSERT INTO career.job_postings (company_id, job_role_id, source_id, title, employment_type, location_text,
                                                status, published_at, expires_at)
               SELECT c.ids[1 + h.c %% %(nc)s], CASE WHEN h.r %% 7 = 0 THEN NULL ELSE r.ids[1 + h.r %% array_length(r.ids, 1)] END,
                      %(src)s, (%(titles)s::text[])[1 + h.t %% %(nt)s] || ' #' || g,
                      (ARRAY['full_time','full_time','contract','intern','part_time', NULL])[1 + h.e %% 6],
                      (%(locs)s::text[])[1 + h.l %% %(nl)s],
                      CASE WHEN h.s %% 10 = 0 THEN 'closed' WHEN h.s %% 53 = 1 THEN 'draft' ELSE 'published' END,
                      now() - (h.p %% 400) * interval '1 day' - (h.p %% 1440) * interval '1 minute',
                      CASE WHEN h.x %% 3 = 0 THEN NULL
                           ELSE now() - (h.p %% 400) * interval '1 day' + (1 + h.x %% 120) * interval '1 day' END
               FROM generate_series(1, %(n)s) g, c, r,
                    -- 열마다 다른 해시(서로 독립인 의사난수) — 나머지 연산끼리 겹쳐 조합 결과가 0이 되는 일을 막음
                    LATERAL (SELECT hashtext('c' || g) & 2147483647 AS c, hashtext('r' || g) & 2147483647 AS r,
                                    hashtext('t' || g) & 2147483647 AS t, hashtext('e' || g) & 2147483647 AS e,
                                    hashtext('l' || g) & 2147483647 AS l, hashtext('s' || g) & 2147483647 AS s,
                                    hashtext('p' || g) & 2147483647 AS p, hashtext('x' || g) & 2147483647 AS x) h""",
            {"nc": companies, "src": src, "titles": TITLES, "nt": len(TITLES), "locs": LOCATIONS, "nl": len(LOCATIONS),
             "n": postings})
        # 마감일 = 게시일 + 1~120일 (CHECK expires_at >= published_at). 오래된 공고는 이미 마감
        admin.execute("ANALYZE career.job_postings")
        admin.execute("ANALYZE career.companies")


def apply_sql(admin_url: str, relative: str) -> None:
    """제안 DDL 파일을 일회용 DB 에 그대로 실행(파라미터 없는 단순 실행 — 주석의 % 를 자리표시자로 보지 않음)."""
    import psycopg
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute((ROOT / relative).read_text(encoding="utf-8"))
        admin.execute("ANALYZE career.job_postings")
        admin.execute("ANALYZE career.companies")


SCENARIOS = {
    "S01 default first page": dict(),
    "S02 q title+company": dict(q="개발자", q_matches_company=True, advanced=True),
    "S03 q rare (company name)": dict(q="합성기업 77", q_matches_company=True, advanced=True),
    "S04 employment contract": dict(employment_types=("contract",), advanced=True),
    "S05 region seoul+gyeonggi": dict(regions=("seoul", "gyeonggi"), advanced=True),
    "S06 region jeju (rare)": dict(regions=("jeju",), advanced=True),
    "S07 posted 7d + full_time": dict(posted_within="7d", employment_types=("full_time",), advanced=True),
    "S08 combo q+type+region+7d": dict(q="개발자", q_matches_company=True, employment_types=("full_time",),
                                      regions=("seoul",), posted_within="7d", advanced=True),
    "S09 expires_at sort (open)": dict(sort="expires_at"),
    "S10 include_closed expires_at": dict(sort="expires_at", include_closed=True),
    "S11 3 companies": dict(company_ids="first3", advanced=True),
    "S12 deep page (after 2000 rows)": dict(deep=True),
}


def make_filter(spec: dict, session: Session) -> tuple[PostingFilter, tuple | None]:
    spec = dict(spec)
    deep = spec.pop("deep", False)
    if spec.get("company_ids") == "first3":
        from sqlalchemy import text
        spec["company_ids"] = tuple(r[0] for r in session.execute(text(
            "SELECT company_id FROM career.companies WHERE name LIKE 'T99 %' ORDER BY name LIMIT 3")))
    base = dict(q=None, company_id=None, job_role_id=None, include_closed=False, sort="-published_at")
    f = PostingFilter(**{**base, **spec})
    after = None
    if deep:
        from sqlalchemy import text
        row = session.execute(text("SELECT published_at, job_posting_id FROM career.job_postings WHERE status='published' "
                                   "AND (expires_at IS NULL OR expires_at > now()) ORDER BY published_at DESC, "
                                   "job_posting_id DESC OFFSET 2000 LIMIT 1")).one()
        after = (row[0], row[1])
    return f, after


def plan_summary(plan: dict) -> dict:
    nodes, indexes, seq = [], set(), set()

    def walk(node):
        nodes.append(node["Node Type"])
        if "Index Name" in node:
            indexes.add(node["Index Name"])
        if node["Node Type"] == "Seq Scan":
            seq.add(node.get("Relation Name"))
        for child in node.get("Plans", []):
            walk(child)
    walk(plan["Plan"])
    return {"execution_ms": round(plan["Execution Time"], 3), "nodes": sorted(set(nodes)), "indexes": sorted(indexes),
            "seq_scan_tables": sorted(seq)}


def measure(engine, now: datetime, repeats: int) -> dict:
    captured = {}

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        captured["sql"], captured["params"] = statement, parameters

    out = {}
    with Session(engine) as session:
        repo = SqlJobPostingRepository(session)
        for name, spec in SCENARIOS.items():
            f, after = make_filter(spec, session)
            for _ in range(3):
                rows = repo.list_postings(f, after, 21, now)
            times = []
            for _ in range(repeats):
                start = time.perf_counter()
                rows = repo.list_postings(f, after, 21, now)
                times.append((time.perf_counter() - start) * 1000)
            sql, params = captured["sql"], captured["params"]
            plan = session.connection().exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params).scalar()
            out[name] = {"rows": len(rows), "p50_ms": round(percentile(times, 50), 3), "p95_ms": round(percentile(times, 95), 3),
                         "max_ms": round(max(times), 3), **plan_summary(plan[0])}
    event.remove(engine, "before_cursor_execute", capture)
    return out


def main(argv=None) -> int:
    import os
    parser = argparse.ArgumentParser(prog="python -m perf.t99_search_bench")
    parser.add_argument("--postings", type=int, default=100_000)
    parser.add_argument("--companies", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    admin_url = os.environ["T16_TEST_ADMIN_URL"]
    guard(admin_url)
    build(admin_url, args.postings, args.companies)
    engine = create_engine(sqlalchemy_url(admin_url))
    now = datetime.now(UTC)
    phases = {}
    try:
        with engine.connect() as conn:
            version = conn.exec_driver_sql("SHOW server_version").scalar()
            counts = dict(conn.exec_driver_sql("SELECT status, count(*) FROM career.job_postings GROUP BY 1").all())
        phases["A_0001_indexes_only"] = measure(engine, now, args.repeats)
        apply_sql(admin_url, "database/proposed/T99_job_search_indexes.sql")
        phases["B_plus_proposed_indexes"] = measure(engine, now, args.repeats)
        apply_sql(admin_url, "database/proposed/T99_job_search_trgm_option.sql")
        phases["C_plus_trgm_option"] = measure(engine, now, args.repeats)
        engine.dispose()
        import psycopg
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute("DROP SCHEMA career CASCADE")
    finally:
        engine.dispose()
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {"postgres": version, "python": platform.python_version(), "os": platform.platform(),
                        "note": "local disposable cluster, single connection, repository-level (no HTTP)"},
        "data": {"postings_by_status": counts, "companies": args.companies, "repeats": args.repeats,
                 "page_size": 20},
        "target": "p95 < 150 ms per query (T98 §7, PROPOSED)",
        "phases": phases,
    }
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
