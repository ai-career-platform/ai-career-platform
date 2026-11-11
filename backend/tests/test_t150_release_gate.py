"""T150 확장 최종 Gate — 판정 규칙 고정(T120 과 같음), T120 P0 이월, 문서·JSON 일치."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = json.loads((ROOT / "docs" / "release" / "t150_gate.json").read_text(encoding="utf-8"))
T120 = json.loads((ROOT / "docs" / "release" / "t120_gate.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "release" / "T150_EXPANSION_FINAL_GATE.md").read_text(encoding="utf-8")
RESULTS = {"PASS", "PARTIAL", "FAIL", "OPEN", "NOT_MEASURED", "NOT_VERIFIED", "NOT_RUN", "N/A"}


def decide(gate: dict) -> str:
    """P0 Gate 가 모두 PASS 이고 PM 승인자가 있어야만 GO."""
    p0_ok = all(g["result"] == "PASS" for g in gate["gates"] if g["p0"])
    return "GO" if p0_ok and gate.get("approved_by", "").strip() else "NO_GO"


def test_gate_values_are_known_and_unique():
    assert {g["result"] for g in GATE["gates"]} <= RESULTS
    assert len({g["id"] for g in GATE["gates"]}) == len(GATE["gates"])


def test_decision_follows_the_rule_and_is_no_go():
    assert GATE["decision"] == decide(GATE) == "NO_GO"
    assert GATE["approved_by"] == ""


def test_go_needs_every_p0_pass_and_an_approver():
    all_pass = {**GATE, "gates": [{**g, "result": "PASS"} for g in GATE["gates"]]}
    assert decide({**all_pass, "approved_by": ""}) == "NO_GO"
    assert decide({**all_pass, "approved_by": "  "}) == "NO_GO"
    assert decide({**all_pass, "approved_by": "PM"}) == "GO"
    for gid in (g["id"] for g in GATE["gates"] if g["p0"]):
        one = {**all_pass, "approved_by": "PM",
               "gates": [{**g, "result": "PARTIAL"} if g["id"] == gid else g for g in all_pass["gates"]]}
        assert decide(one) == "NO_GO", gid


def test_unresolved_t120_p0_failures_are_carried_not_upgraded():
    t120_failed = {g["id"] for g in T120["gates"] if g["p0"] and g["result"] != "PASS"}
    assert set(GATE["carried_from_t120"]) <= t120_failed | {"E5", "E6"}
    by_id = {g["id"]: g for g in GATE["gates"]}
    assert by_id["F4"]["result"] == "FAIL"          # E5 migration
    assert by_id["F11"]["result"] == "FAIL"         # E6 vulnerabilities
    # 선행 일감이 열린 PR·미착수인데 선행 Gate 를 PASS 로 올리지 않는다
    assert any(v.startswith(("PR_", "NOT_STARTED")) for v in GATE["prerequisites"].values())
    assert by_id["F13"]["result"] != "PASS"


def test_document_matches_json():
    assert f"**판정: {GATE['decision']}**" in DOC
    assert GATE["main_sha"] in DOC and str(GATE["publish_run_id"]) in DOC
    for image in GATE["images"].values():
        assert image in DOC
    for g in GATE["gates"]:
        row = re.search(rf"^\| {g['id']} \|[^|]+\| \*\*([^*]+)\*\*", DOC, re.M)
        assert row, g["id"]
        assert re.split(r"[ (]", row.group(1))[0] == g["result"], (g["id"], row.group(1))
    assert GATE["staging_running_digest"] == "NOT_VERIFIED" and "NOT_VERIFIED" in DOC
