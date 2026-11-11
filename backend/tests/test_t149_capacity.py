"""T149 비용·용량 계획: 가정의 근거 표시, 결정적 예측, 문서↔계산 일치, 읽기 전용 측정."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("t149_capacity", ROOT / "scripts" / "ops" / "t149_capacity.py")
cap = importlib.util.module_from_spec(_spec)
sys.modules["t149_capacity"] = cap
_spec.loader.exec_module(cap)

CAP_DIR = ROOT / "docs" / "ops" / "capacity"
ASSUMPTIONS = json.loads((CAP_DIR / "t149_assumptions.json").read_text(encoding="utf-8"))
MEASURED = json.loads((CAP_DIR / "t149_measured_local.json").read_text(encoding="utf-8"))
GIB = 1024 ** 3


def _leaves(node, path=""):
    if isinstance(node, dict) and "value" in node:
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)


# ------------------------------------------------------------------ 가정의 근거
def test_every_assumption_has_basis_and_note():
    assert cap.validate_assumptions(ASSUMPTIONS) == []
    leaves = dict(_leaves({k: v for k, v in ASSUMPTIONS.items() if k != "scenarios"}))
    assert len(leaves) >= 20
    assert all(v["basis"] in {"measured", "estimated", "proposed"} for v in leaves.values())


def test_ai_cost_inputs_are_never_presented_as_measured():
    # T110(AI 운영)이 미착수라 실제 사용량·단가가 없다.
    for path, leaf in _leaves(ASSUMPTIONS["ai"]):
        assert leaf["basis"] == "estimated", path
    assert "not a quote" in ASSUMPTIONS["ai"]["usd_per_million_input"]["note"]
    assert "T110" in ASSUMPTIONS["ai"]["calls_per_user_month"]["note"]


@pytest.mark.parametrize("mutate, message", [
    (lambda a: a["storage"]["document_avg_bytes"].pop("basis"), "basis"),
    (lambda a: a["storage"]["document_avg_bytes"].update(basis="guess"), "basis"),
    (lambda a: a["logs"]["retention_days"].update(note=""), "note"),
    (lambda a: a["crawler"]["new_postings_per_day"].update(value=-1), ">= 0"),
    (lambda a: a["ai"]["calls_per_user_month"].update(value=float("nan")), ">= 0"),
    (lambda a: a["ai"]["calls_per_user_month"].update(value=True), ">= 0"),
    (lambda a: a["scenarios"][0].update(users_start=500), "users_start"),
])
def test_invalid_assumptions_are_rejected(mutate, message):
    bad = copy.deepcopy(ASSUMPTIONS)
    mutate(bad)
    problems = cap.validate_assumptions(bad)
    assert problems and any(message in p for p in problems)
    with pytest.raises(ValueError):
        cap.project(bad, MEASURED)


# ------------------------------------------------------------------ 측정 파일
def test_measured_file_is_synthetic_local_and_has_four_scales():
    assert MEASURED["basis"] == "measured"
    assert "synthetic" in MEASURED["data"]
    labels = [r["label"] for r in MEASURED["runs"]]
    assert labels == ["s0", "s1", "s2", "s3"]
    sizes = [r["database_bytes"] for r in MEASURED["runs"]]
    assert sizes == sorted(sizes) and len(set(sizes)) == 4          # 규모가 커질수록 커진다
    for run in MEASURED["runs"]:
        assert all(r.startswith("t149_local_") for r in [run["database"]])
        assert run["career_rows"] == sum(t["rows"] for t in run["tables"].values())
        assert 0 < run["dump_bytes"] < run["database_bytes"]


# ------------------------------------------------------------------ 예측
def test_projection_is_deterministic_and_matches_committed_json():
    first = cap.project(ASSUMPTIONS, MEASURED)
    assert first == cap.project(copy.deepcopy(ASSUMPTIONS), copy.deepcopy(MEASURED))
    saved = json.loads((CAP_DIR / "t149_projection.json").read_text(encoding="utf-8"))
    assert first == saved


def test_projection_grows_with_users():
    result = {s["scenario"]: s for s in cap.project(ASSUMPTIONS, MEASURED)["scenarios"]}
    for key in ("db_gib", "documents_gib", "logs_gib", "backups_gib", "total_storage_gib", "ai_usd_per_month"):
        assert result["poc"][key] < result["class"][key] < result["growth"][key], key
    # 크롤러 원본 HTML은 사용자 수와 무관(수집량·보존일로만 결정)
    assert result["poc"]["raw_html_gib"] == result["growth"]["raw_html_gib"]


def test_hand_recomputed_numbers():
    result = {s["scenario"]: s for s in cap.project(ASSUMPTIONS, MEASURED)["scenarios"]}
    # AI: 호출당 2000×3/1e6 + 500×15/1e6 = 0.0135 USD, 사용자당 월 20회, 100명
    assert result["poc"]["ai_usd_per_month"] == pytest.approx(100 * 20 * 0.0135)
    # 원본 HTML: 200건/일 × 1.05쪽 × 150,000 B × 30일
    assert result["poc"]["raw_html_gib"] == round(200 * 1.05 * 150_000 * 30 / GIB, 3)
    # 문서: 10,000명 × 2개 × 350,000 B
    assert result["growth"]["documents_gib"] == round(10_000 * 2 * 350_000 / GIB, 3)
    # 로그: 10,000명 × 20요청 × 400 B × 30일
    assert result["growth"]["logs_gib"] == round(10_000 * 20 * 400 * 30 / GIB, 3)
    # 백업 = DB × 덤프 비율 × 14개 보관
    g = result["growth"]
    proj = cap.project(ASSUMPTIONS, MEASURED)
    assert g["backups_gib"] == pytest.approx(g["db_gib"] * proj["dump_ratio"] * 14, rel=2e-3)
    assert g["disk_needed_gib"] == pytest.approx(g["total_storage_gib"] / 0.7, rel=1e-3)


def test_bytes_per_row_come_from_the_largest_measured_scale():
    proj = cap.project(ASSUMPTIONS, MEASURED)
    s3 = MEASURED["runs"][-1]["tables"]["behavior_events"]
    assert proj["bytes_per_row"]["behavior_events"] == round(s3["total_bytes"] / s3["rows"], 1)
    assert proj["dump_ratio"] == round(MEASURED["runs"][-1]["dump_bytes"] / MEASURED["runs"][-1]["database_bytes"], 4)


# ------------------------------------------------------------------ 문서 ↔ 계산
def test_plan_document_matches_projection():
    assert cap.check() == []


def test_tampered_document_is_detected(tmp_path):
    doc = (ROOT / "docs" / "ops" / "CAPACITY_COST_PLAN.md").read_text(encoding="utf-8")
    growth = next(s for s in cap.project(ASSUMPTIONS, MEASURED)["scenarios"] if s["scenario"] == "growth")
    needle = f" {growth['ai_usd_per_month']:,} "
    row = next(line for line in doc.splitlines() if line.startswith("| growth |"))
    assert needle in row.replace("|", " | ")
    tampered = doc.replace(row, row.replace(f"{growth['ai_usd_per_month']:,}", "99.0"))
    (tmp_path / "plan.md").write_text(tampered, encoding="utf-8")
    problems = cap.check(doc=tmp_path / "plan.md")
    assert any("growth" in p and "ai_usd_per_month" in p for p in problems)


def test_measured_vs_estimated_is_stated_in_the_document():
    doc = (ROOT / "docs" / "ops" / "CAPACITY_COST_PLAN.md").read_text(encoding="utf-8")
    for word in ("실측", "추정", "제안", "RTO", "RPO", "PROPOSED"):
        assert word in doc, word
    assert re.search(r"T110.*(NOT_STARTED|미착수)", doc)


# ------------------------------------------------------------------ 측정 안전장치
def test_measure_refuses_remote_hosts():
    pytest.importorskip("psycopg")
    with pytest.raises(SystemExit, match="loopback"):
        cap.measure("postgresql://u@192.0.2.30:5432/career", "remote")


def test_activity_sql_has_a_disposable_database_guard():
    sql = (ROOT / "scripts" / "ops" / "t149_activity_rows.sql").read_text(encoding="utf-8")
    guard_at = sql.index("current_database() NOT LIKE 't149\\_local\\_%'")
    assert guard_at < sql.index("INSERT INTO")
    assert "ON_ERROR_STOP" in sql


from tests.security.security_pg import disposable_pg, requires_pg  # noqa: E402


@pytest.fixture
def pg(monkeypatch):
    import os
    for ctx in disposable_pg(monkeypatch, write_tables=(), migrations=("0001", "0002", "0003")):
        yield ctx.db, os.environ["T16_TEST_ADMIN_URL"]


@requires_pg
def test_measure_is_read_only_and_counts_rows(pg):
    db, url = pg
    db.execute("INSERT INTO career.model_versions (model_code, version, kind) VALUES ('t149_test', '0', 'rule')")
    before = db.execute("SELECT count(*) FROM career.model_versions").fetchone()[0]
    result = cap.measure(url, "pg-test")
    assert db.execute("SELECT count(*) FROM career.model_versions").fetchone()[0] == before
    assert result["tables"]["model_versions"]["rows"] == before
    assert len(result["tables"]) == 51
    assert result["career_bytes"] <= result["database_bytes"]


@requires_pg
def test_activity_sql_guard_refuses_a_non_t149_database(pg):
    db, _ = pg
    sql = (ROOT / "scripts" / "ops" / "t149_activity_rows.sql").read_text(encoding="utf-8")
    guard = sql[sql.index("DO $$"):sql.index("END $$;") + len("END $$;")]
    with pytest.raises(Exception, match="refused"):
        db.execute(guard)
