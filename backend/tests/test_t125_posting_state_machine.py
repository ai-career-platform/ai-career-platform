"""T125 기업 공고 상태 기계(PROPOSED) — 검수 우회 금지·종료 상태·사유·T121 권한 일치 시험."""

import json
from collections import deque
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SM = json.loads((ROOT / "docs" / "enterprise" / "t125_posting_state_machine.json").read_text(encoding="utf-8"))
MATRIX = json.loads((ROOT / "docs" / "enterprise" / "t121_role_matrix.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "enterprise" / "T125_COMPANY_POSTING_POLICY.md").read_text(encoding="utf-8")
ACTIONS = {a["action"]: a["decisions"] for a in MATRIX["actions"]}
STATES = SM["states"]
TRANSITIONS = SM["transitions"]
COMPANY = {"company_member", "company_owner"}


def allowed(state_from, state_to):
    return [t for t in TRANSITIONS if t["from"] == state_from and t["to"] == state_to]


def test_machine_is_proposed_and_well_formed():
    assert SM["status"] == "PROPOSED" and SM["initial"] == "draft"
    for t in TRANSITIONS:
        assert t["from"] in STATES and t["to"] in STATES and t["actors"], t
    pairs = [(t["from"], t["to"]) for t in TRANSITIONS]
    assert len(pairs) == len(set(pairs)), "중복 전이"


def test_every_state_is_reachable_from_draft():
    seen, queue = {"draft"}, deque(["draft"])
    while queue:
        current = queue.popleft()
        for t in TRANSITIONS:
            if t["from"] == current and t["to"] not in seen:
                seen.add(t["to"])
                queue.append(t["to"])
    assert seen == set(STATES)


def test_p_inv1_company_roles_never_publish():
    for t in TRANSITIONS:
        if t["to"] == "published":
            assert not COMPANY & set(t["actors"]), t


def test_p_inv2_publish_and_reject_are_admin_only_and_not_self():
    for action in ("posting.publish", "posting.reject"):
        (t,) = [t for t in TRANSITIONS if t["action"] == action]
        assert t["actors"] == ["admin"] and "not_member_of_org" in t["guards"]


def test_p_inv3_only_publish_changes_the_public_table():
    for t in TRANSITIONS:
        if "public_posting_upsert" in t["effects"]:
            assert t["action"] == "posting.publish"
    public = {s for s, meta in STATES.items() if meta["public"]}
    assert public == {"published"}
    assert SM["revision_flow"]["public_changes_only_on"] == "posting.publish"


@pytest.mark.parametrize("action", ["posting.reject", "posting.takedown"])
def test_p_inv4_reject_and_takedown_require_reason(action):
    (t,) = [t for t in TRANSITIONS if t["action"] == action]
    assert "reason_code_required" in t["guards"]


def test_p_inv5_terminal_states_have_no_outgoing_transitions():
    terminal = {s for s, meta in STATES.items() if meta["terminal"]}
    assert terminal == {"closed", "expired", "taken_down"}
    assert [t for t in TRANSITIONS if t["from"] in terminal] == []


def test_p_inv6_admin_never_authors_content():
    for t in TRANSITIONS:
        if t["action"] in {"posting.draft_edit", "posting.submit_review", "posting.withdraw_review"}:
            assert "admin" not in t["actors"], t


def test_p_inv7_every_human_transition_checks_version():
    for t in TRANSITIONS:
        if t["actors"] != ["system"] and t["action"] != "posting.takedown":
            assert "version_match" in t["guards"], t


def test_p_inv8_submit_and_publish_need_an_active_org():
    for action in ("posting.submit_review", "posting.publish"):
        (t,) = [t for t in TRANSITIONS if t["action"] == action]
        assert "org_active" in t["guards"]


@pytest.mark.parametrize(("start", "end"), [
    ("draft", "published"), ("rejected", "published"), ("rejected", "pending_review"),
    ("closed", "published"), ("expired", "published"), ("taken_down", "published"), ("draft", "closed"),
])
def test_shortcuts_are_not_allowed(start, end):
    assert allowed(start, end) == []


def test_transition_actors_match_t121_matrix():
    for t in TRANSITIONS:
        if t["action"].startswith("system."):
            continue
        decisions = ACTIONS[t["action"]]
        for actor in t["actors"]:
            assert decisions[actor] in {"allow", "own"}, (t["action"], actor)
        for role, decision in decisions.items():
            if role in COMPANY | {"admin"} and decision in {"allow", "own"}:
                assert role in t["actors"], (t["action"], role)


def test_reason_codes_and_limits_are_documented():
    for code in SM["reject_reason_codes"] + SM["takedown_reason_codes"]:
        assert f"`{code}`" in DOC, code
    assert SM["limits"]["max_publish_days"] == 60 and "60일" in DOC
    for invariant in SM["invariants"]:
        assert invariant.split(" ", 1)[0] in DOC
    assert SM["source"]["data_source_code"] == "company_direct" and "company_direct" in DOC
