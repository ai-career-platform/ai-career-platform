"""T149 비용·용량 측정과 성장 예측.

- measure : 로컬(loopback) 일회용 DB의 표별 크기·행 수·행당 바이트를 **읽기 전용**으로 잰다. `--dump`면
            T114와 같은 옵션(pg_dump -Fc --no-owner --no-privileges)으로 덤프 크기도 재고 덤프는 지운다.
- project : 측정값(measured) + 가정(assumptions)으로 시나리오별 12개월 용량·비용을 결정적으로 계산한다.
- check   : 계획 문서와 예측 JSON이 같은 숫자인지 확인한다(문서가 계산과 어긋나면 exit 2).

    python scripts/ops/t149_capacity.py measure --db-url postgresql://u@127.0.0.1:55496/t149_local_s3 --label s3 --dump
    python scripts/ops/t149_capacity.py project --assumptions docs/ops/capacity/t149_assumptions.json \
        --measured docs/ops/capacity/t149_measured_local.json --out docs/ops/capacity/t149_projection.json
    python scripts/ops/t149_capacity.py check

측정은 합성 데이터 기준이고, 예측의 사용자 활동·단가·HTML 크기는 **가정**이다. 출력의 `basis`로 구분한다.
운영·Staging DB에는 연결하지 않는다(loopback만 허용, 원격은 거부).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPACITY_DIR = ROOT / "docs" / "ops" / "capacity"
PLAN_DOC = ROOT / "docs" / "ops" / "CAPACITY_COST_PLAN.md"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
GIB = 1024 ** 3
BASIS = {"measured", "estimated", "proposed"}


# ---------------------------------------------------------------- measure (읽기 전용)
def _loopback_only(url: str) -> dict:
    from psycopg.conninfo import conninfo_to_dict
    info = conninfo_to_dict(url)
    if info.get("host") not in LOOPBACK:
        raise SystemExit("refused: loopback (disposable local database) only")
    return info


def measure(url: str, label: str, dump: bool = False) -> dict:
    import psycopg
    info = _loopback_only(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        db_bytes = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        names = [r[0] for r in conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'career' AND c.relkind = 'r' ORDER BY c.relname").fetchall()]
        tables = {}
        for name in names:
            rows = conn.execute(f'SELECT count(*) FROM career."{name}"').fetchone()[0]
            total = conn.execute("SELECT pg_total_relation_size(%s::regclass)", (f'career."{name}"',)).fetchone()[0]
            tables[name] = {"rows": rows, "total_bytes": total,
                            "bytes_per_row": round(total / rows, 1) if rows else None}
    result = {"label": label, "database": info.get("dbname"), "database_bytes": db_bytes,
              "career_bytes": sum(t["total_bytes"] for t in tables.values()),
              "career_rows": sum(t["rows"] for t in tables.values()), "tables": tables}
    if dump:
        result["dump_bytes"] = _dump_size(url)
    return result


def _dump_size(url: str) -> int:
    pg_dump = shutil.which("pg_dump") or os.environ.get("PG_DUMP", "pg_dump")
    with tempfile.TemporaryDirectory(prefix="t149_dump_") as tmp:
        target = Path(tmp) / "measure.dump"
        subprocess.run([pg_dump, "-Fc", "--no-owner", "--no-privileges", "-d", url, "-f", str(target)],
                       check=True, capture_output=True)
        return target.stat().st_size


# ---------------------------------------------------------------- project (결정적 계산)
def _value(entry):
    return entry["value"] if isinstance(entry, dict) else entry


def validate_assumptions(a: dict) -> list[str]:
    """모든 가정에 근거(basis)가 있는지, 값이 음수가 아닌지 확인한다."""
    problems = []

    def walk(node, path):
        if isinstance(node, dict) and "value" in node:
            if node.get("basis") not in BASIS:
                problems.append(f"{path}: basis must be one of {sorted(BASIS)}")
            if not node.get("note"):
                problems.append(f"{path}: note (source or reason) is required")
            v = node["value"]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or not math.isfinite(v):
                problems.append(f"{path}: value must be a finite number >= 0")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
    walk({k: v for k, v in a.items() if k != "scenarios"}, "")
    for s in a.get("scenarios", []):
        if not (0 < s["users_start"] <= s["users_month12"]):
            problems.append(f"scenario {s['name']}: need 0 < users_start <= users_month12")
    return problems


def _fit_per_row(measured: dict, table: str) -> float:
    """가장 큰 규모에서 잰 행당 바이트(페이지·인덱스 고정 비용이 가장 덜 섞임)."""
    largest = max(measured["runs"], key=lambda r: r["career_rows"])
    t = largest["tables"][table]
    if not t["rows"]:
        raise ValueError(f"table {table} has no measured rows")
    return t["total_bytes"] / t["rows"]


def _dump_ratio(measured: dict) -> float:
    largest = max(measured["runs"], key=lambda r: r["career_rows"])
    return largest["dump_bytes"] / largest["database_bytes"]


def project(a: dict, measured: dict) -> dict:
    problems = validate_assumptions(a)
    if problems:
        raise ValueError("; ".join(problems))
    per_row = {t: _fit_per_row(measured, t) for t in a["activity_per_user_month"]}
    per_row.update({t: _fit_per_row(measured, t) for t in ("users", "user_profiles", "user_skills", "user_documents",
                                                            "job_postings", "job_posting_skills", "companies")})
    base_db = min(measured["runs"], key=lambda r: r["career_rows"])["database_bytes"]
    dump_ratio = _dump_ratio(measured)
    st = {k: _value(v) for k, v in a["storage"].items()}
    ai = {k: _value(v) for k, v in a["ai"].items()}
    crawler = {k: _value(v) for k, v in a["crawler"].items()}
    logs = {k: _value(v) for k, v in a["logs"].items()}
    backup = {k: _value(v) for k, v in a["backup"].items()}
    activity = {k: _value(v) for k, v in a["activity_per_user_month"].items()}
    profile = {k: _value(v) for k, v in a["per_user_static"].items()}

    out = []
    for s in a["scenarios"]:
        months = 12
        # 사용자 수는 시작 → 12개월 차로 선형 증가. 누적 사용자-월 = 매달 사용자 수의 합.
        users = [s["users_start"] + (s["users_month12"] - s["users_start"]) * m / (months - 1) for m in range(months)]
        user_months = sum(users)
        u12 = users[-1]
        rows = {t: activity[t] * user_months for t in activity}
        rows["users"] = rows["user_profiles"] = u12
        rows["user_skills"] = u12 * profile["user_skills"]
        rows["user_documents"] = u12 * profile["documents"]
        # 공고 행은 마감 뒤에도 남는다(삭제 정책 미정). 12개월 누적.
        postings = crawler["new_postings_per_day"] * 365 / 12 * months + crawler["company_postings_total"]
        rows["job_postings"] = postings
        rows["job_posting_skills"] = postings * crawler["skills_per_posting"]
        rows["companies"] = crawler["companies"]
        db_bytes = base_db + sum(rows[t] * per_row[t] for t in rows)
        raw_pages_per_day = crawler["new_postings_per_day"] * crawler["pages_per_posting"]
        raw_bytes = raw_pages_per_day * crawler["html_bytes_per_page"] * min(crawler["raw_retention_days"], 365)
        doc_bytes = u12 * profile["documents"] * st["document_avg_bytes"]
        log_bytes = u12 * logs["requests_per_user_day"] * logs["bytes_per_line"] * logs["retention_days"]
        backup_bytes = db_bytes * dump_ratio * backup["copies"]
        ai_month = u12 * ai["calls_per_user_month"] * (
            ai["input_tokens_per_call"] * ai["usd_per_million_input"]
            + ai["output_tokens_per_call"] * ai["usd_per_million_output"]) / 1_000_000
        total = db_bytes + raw_bytes + doc_bytes + log_bytes + backup_bytes
        out.append({
            "scenario": s["name"], "users_month12": round(u12), "user_months": round(user_months),
            "db_gib": round(db_bytes / GIB, 3), "raw_html_gib": round(raw_bytes / GIB, 3),
            "documents_gib": round(doc_bytes / GIB, 3), "logs_gib": round(log_bytes / GIB, 3),
            "backups_gib": round(backup_bytes / GIB, 3), "total_storage_gib": round(total / GIB, 3),
            "disk_needed_gib": round(total / GIB / st["max_disk_utilization"], 3),
            "ai_usd_per_month": round(ai_month, 2),
            "basis": {"bytes_per_row": "measured (synthetic, local PostgreSQL)", "activity_and_prices": "estimated"},
        })
    return {"tool": "t149_capacity", "months": 12, "dump_ratio": round(dump_ratio, 4),
            "base_database_bytes": base_db, "bytes_per_row": {k: round(v, 1) for k, v in sorted(per_row.items())},
            "scenarios": out}


# ---------------------------------------------------------------- check (문서 ↔ 계산)
def check(doc: Path = PLAN_DOC, capacity_dir: Path = CAPACITY_DIR) -> list[str]:
    assumptions = json.loads((capacity_dir / "t149_assumptions.json").read_text(encoding="utf-8"))
    measured = json.loads((capacity_dir / "t149_measured_local.json").read_text(encoding="utf-8"))
    saved = json.loads((capacity_dir / "t149_projection.json").read_text(encoding="utf-8"))
    fresh = project(assumptions, measured)
    problems = []
    if fresh != saved:
        problems.append("t149_projection.json is stale: rerun `project`")
    text = doc.read_text(encoding="utf-8")
    for s in fresh["scenarios"]:
        row = next((line for line in text.splitlines() if line.startswith(f"| {s['scenario']} |")), None)
        if row is None:
            problems.append(f"doc has no projection row for {s['scenario']}")
            continue
        for key in ("db_gib", "raw_html_gib", "documents_gib", "logs_gib", "backups_gib", "total_storage_gib", "ai_usd_per_month"):
            if f" {s[key]:,} " not in row.replace("|", " | "):
                problems.append(f"doc row {s['scenario']}: {key}={s[key]:,} missing")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--db-url", required=True)
    m.add_argument("--label", required=True)
    m.add_argument("--dump", action="store_true")
    pr = sub.add_parser("project")
    pr.add_argument("--assumptions", type=Path, default=CAPACITY_DIR / "t149_assumptions.json")
    pr.add_argument("--measured", type=Path, default=CAPACITY_DIR / "t149_measured_local.json")
    pr.add_argument("--out", type=Path)
    sub.add_parser("check")
    args = p.parse_args(argv)
    if args.command == "measure":
        print(json.dumps(measure(args.db_url, args.label, args.dump), ensure_ascii=False, indent=2))
        return 0
    if args.command == "project":
        result = project(json.loads(args.assumptions.read_text(encoding="utf-8")),
                         json.loads(args.measured.read_text(encoding="utf-8")))
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0
    problems = check()
    for line in problems:
        print("FAIL", line)
    print("T149_CAPACITY_CHECK=" + ("FAIL" if problems else "PASS"))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
