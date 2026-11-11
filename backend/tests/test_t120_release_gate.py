"""T120 확장 릴리스 Gate — 판정 규칙 고정: P0 가 PASS 가 아니면 NO_GO, GO 는 PM 승인자 필수, 문서·JSON 일치."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = json.loads((ROOT / "docs" / "release" / "t120_gate.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "release" / "EXPANSION_RELEASE_GATE.md").read_text(encoding="utf-8")
RESULTS = {"PASS", "PARTIAL", "FAIL", "OPEN", "NOT_MEASURED", "NOT_VERIFIED", "NOT_RUN", "N/A"}


def decide(gate: dict) -> str:
    """P0 Gate 가 모두 PASS 이고 PM 승인자가 있어야만 GO."""
    p0_ok = all(g["result"] == "PASS" for g in gate["gates"] if g["p0"])
    return "GO" if p0_ok and gate.get("approved_by", "").strip() else "NO_GO"


def test_gate_values_are_known():
    assert {g["result"] for g in GATE["gates"]} <= RESULTS
    assert len({g["id"] for g in GATE["gates"]}) == len(GATE["gates"])


def test_decision_follows_the_rule():
    assert GATE["decision"] == decide(GATE) == "NO_GO"


def test_go_needs_every_p0_pass_and_an_approver():
    all_pass = {**GATE, "gates": [{**g, "result": "PASS"} for g in GATE["gates"]]}
    assert decide({**all_pass, "approved_by": ""}) == "NO_GO"
    assert decide({**all_pass, "approved_by": "   "}) == "NO_GO"
    assert decide({**all_pass, "approved_by": "PM"}) == "GO"
    one_fail = {**all_pass, "approved_by": "PM"}
    one_fail["gates"] = [{**g, "result": "PARTIAL"} if g["id"] == "E9" else g for g in all_pass["gates"]]
    assert decide(one_fail) == "NO_GO"


def test_document_matches_json():
    assert f"**판정: {GATE['decision']}**" in DOC
    assert GATE["main_sha"] in DOC
    for image in GATE["images"].values():
        assert image in DOC
    for g in GATE["gates"]:
        row = re.search(rf"^\| {g['id']} \|[^|]+\| \*\*([^*]+)\*\*", DOC, re.M)
        assert row, g["id"]
        assert re.split(r"[ (]", row.group(1))[0] == g["result"], (g["id"], row.group(1))
    assert "NOT_VERIFIED" in DOC and GATE["staging_running_digest"] == "NOT_VERIFIED"
