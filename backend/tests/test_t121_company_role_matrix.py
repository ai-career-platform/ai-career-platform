"""T121 기업 역할 정책(PROPOSED) — 권한 매트릭스 불변 조건과 문서 일치.

구현이 아니라 정책 원본(docs/enterprise/t121_role_matrix.json)의 일관성을 고정한다.
T123·T126·T129 구현은 이 매트릭스를 그대로 읽어 같은 결정을 내려야 한다.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = json.loads((ROOT / "docs" / "enterprise" / "t121_role_matrix.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "enterprise" / "T121_COMPANY_ROLE_POLICY.md").read_text(encoding="utf-8")
ROLES = ["anonymous", "job_seeker", "company_member", "company_owner", "admin"]
COMPANY = ["company_member", "company_owner"]
ACTIONS = {a["action"]: a["decisions"] for a in MATRIX["actions"]}
GRANTING = {"allow", "own", "self", "consented"}
RANK = {"deny": 0, "consented": 1, "self": 1, "own": 2, "allow": 3}


def test_matrix_is_proposed_and_complete():
    assert MATRIX["status"] == "PROPOSED"
    assert set(MATRIX["roles"]) == set(ROLES)
    assert len(ACTIONS) == len(MATRIX["actions"]), "중복 action"
    for action, decisions in ACTIONS.items():
        assert set(decisions) == set(ROLES), action
        assert set(decisions.values()) <= set(MATRIX["decision_values"]), action


def test_inv1_company_roles_are_organization_scoped():
    for role in COMPANY:
        assert MATRIX["roles"][role]["scope"] == "organization"
    assert MATRIX["roles"]["admin"]["scope"] == "global"


def test_inv2_company_roles_never_get_admin_actions():
    for action, decisions in ACTIONS.items():
        if action.startswith("admin."):
            assert all(decisions[r] == "deny" for r in COMPANY + ["job_seeker", "anonymous"]), action


@pytest.mark.parametrize("action", ["posting.publish", "posting.reject", "posting.takedown", "org.verify", "org.suspend"])
def test_inv3_only_admin_moderates(action):
    decisions = ACTIONS[action]
    assert decisions["admin"] == "allow"
    assert [r for r in ROLES if r != "admin" and decisions[r] != "deny"] == []


@pytest.mark.parametrize("action", ["candidate.view_private_profile", "candidate.search", "candidate.contact",
                                    "candidate.view_applications"])
def test_inv4_candidate_private_data_is_denied_to_everyone(action):
    assert set(ACTIONS[action].values()) == {"deny"}


def test_public_profile_is_consent_bound_for_everyone_including_admin():
    assert set(ACTIONS["candidate.view_public_profile"].values()) == {"consented"}


def test_inv5_company_resource_actions_are_own_scoped_never_global():
    for action, decisions in ACTIONS.items():
        if action.split(".")[0] in {"org", "member", "posting"} and action not in {"org.register", "posting.view_public"}:
            for role in COMPANY:
                assert decisions[role] in {"own", "self", "deny"}, (action, role)


def test_member_is_never_more_permissive_than_owner():
    for action, decisions in ACTIONS.items():
        assert RANK[decisions["company_member"]] <= RANK[decisions["company_owner"]], action


def test_owner_only_actions():
    for action in ("member.invite", "member.invite_resend", "member.invite_revoke", "member.change_role",
                   "member.remove", "org.update_profile"):
        assert ACTIONS[action]["company_owner"] == "own" and ACTIONS[action]["company_member"] == "deny", action


def test_job_seeker_company_surface_is_register_and_accept_only():
    allowed = {a for a, d in ACTIONS.items() if d["job_seeker"] in GRANTING}
    assert allowed == {"org.register", "invite.accept", "posting.view_public", "candidate.view_public_profile"}
    assert ACTIONS["invite.accept"]["job_seeker"] == "self"


def test_anonymous_sees_only_public_postings_and_consented_profiles():
    allowed = {a for a, d in ACTIONS.items() if d["anonymous"] in GRANTING}
    assert allowed == {"posting.view_public", "candidate.view_public_profile"}


def test_inv9_admin_does_not_author_company_postings():
    for action in ("posting.draft_create", "posting.draft_edit", "posting.submit_review", "posting.withdraw_review"):
        assert ACTIONS[action]["admin"] == "deny", action


def test_inv8_org_status_rules_only_narrow_permissions():
    rules = MATRIX["org_status_rules"]
    assert rules["active"] == "*" and rules["closed"] == []
    for status in ("pending", "suspended"):
        assert set(rules[status]) <= set(ACTIONS), status
        assert "posting.submit_review" not in rules[status] and "member.invite" not in rules[status]
    assert "posting.draft_create" in rules["pending"] and "posting.draft_create" not in rules["suspended"]


def test_invariants_are_documented_and_doc_lists_every_action():
    for invariant in MATRIX["invariants"]:
        assert invariant.split(" ", 1)[0] in DOC
    for action in ACTIONS:
        assert f"`{action}`" in DOC, action
    assert "PROPOSED" in DOC.splitlines()[2]
