"""T141 개인정보 요청 정책(PROPOSED) — 상태 기계·재인증·반출 제외 열·보존 분기·문서 일치 시험."""

import json
import re
from collections import deque
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "docs" / "privacy" / "t141_data_subject_requests.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "privacy" / "T141_DATA_SUBJECT_REQUEST_POLICY.md").read_text(encoding="utf-8")
SCHEMA = (ROOT / "database" / "migrations" / "0001_initial_schema.sql").read_text(encoding="utf-8")
AUDIT = (ROOT / "docs" / "security" / "AUDIT_EVENT_CONTRACT.md").read_text(encoding="utf-8")

STATES = POLICY["states"]
TRANSITIONS = POLICY["transitions"]
TERMINAL = {s for s, meta in STATES.items() if meta["terminal"]}


def table_columns(table: str) -> set[str]:
    match = re.search(rf"CREATE TABLE career\.{table} \((.*?)\n\);", SCHEMA, re.S)
    assert match, table
    return {line.split()[0] for line in match.group(1).splitlines()
            if line.strip() and not line.strip().startswith(("PRIMARY", "CHECK", "FOREIGN", "UNIQUE", "CONSTRAINT"))}


def test_policy_is_proposed_and_well_formed():
    assert POLICY["status"] == "PROPOSED"
    assert set(POLICY["request_types"]) == {"access", "rectification", "erasure", "export"}
    assert set(POLICY["initial"].values()) <= set(STATES)
    for t in TRANSITIONS:
        assert t["from"] in STATES and t["to"] in STATES and t["actors"], t
        assert set(t["actors"]) <= set(POLICY["actors"]), t
    pairs = [(t["from"], t["to"]) for t in TRANSITIONS]
    assert len(pairs) == len(set(pairs)), "중복 전이"


def test_every_state_reachable_from_an_initial_state():
    seen = set(POLICY["initial"].values())
    queue = deque(seen)
    while queue:
        current = queue.popleft()
        for t in TRANSITIONS:
            if t["from"] == current and t["to"] not in seen:
                seen.add(t["to"])
                queue.append(t["to"])
    assert seen == set(STATES)


def test_d_inv1_requester_actions_are_owner_only():
    for t in TRANSITIONS:
        if "requester" in t["actors"]:
            assert "owner_only" in t["guards"], t


def test_d_inv2_sensitive_types_require_reauth_within_ten_minutes():
    for code in ("access", "erasure", "export"):
        assert POLICY["request_types"][code]["reauth_required"] is True
    assert POLICY["identity_verification"]["self_service"]["reauth_max_age_minutes"] == 10
    assert POLICY["identity_verification"]["self_service"]["reauth_bound_to"] == "session_id"


def test_d_inv3_never_exported_columns_cover_secrets_and_exist_in_schema():
    never = set(POLICY["never_export_columns"])
    assert {"password_hash", "refresh_token_hash", "token_hash", "client_ip_hash", "storage_key"} <= never
    seen = set()
    for cat in POLICY["data_categories"]:
        for table in cat["tables"]:
            seen |= table_columns(table)
    # T83이 audit_events에 추가 제안한 열(아직 0001에 없음)도 인정한다.
    t83_proposed = {"client_ip_hash", "row_hash"}
    assert all(f"`{c}`" in AUDIT for c in t83_proposed)
    assert never <= seen | t83_proposed, never - seen  # 오타로 아무것도 막지 않는 일을 막는다
    for cat in POLICY["data_categories"]:
        if cat["export"] in {"include", "metadata_and_files"}:
            cols = set().union(*(table_columns(t) for t in cat["tables"]))
            leaked = (cols & never) - set(cat["excluded_columns"])
            assert not leaked, (cat["category"], leaked)
    (cred,) = [c for c in POLICY["data_categories"] if c["category"] == "credentials"]
    assert cred["export"] == "exclude"


def test_data_categories_reference_real_tables_and_cover_user_tables():
    listed = {t for c in POLICY["data_categories"] for t in c["tables"]}
    for table in listed:
        assert f"CREATE TABLE career.{table} " in SCHEMA, table
    user_tables = set(re.findall(r"CREATE TABLE career\.(\w+) \([^;]*?(?:user_id|owner_user_id) uuid", SCHEMA, re.S))
    # 사용자 소유 행이 있는 표는 모두 반출·삭제 분기를 가져야 한다(누락 = 삭제 안 되는 개인정보).
    missing = {t for t in user_tables if t not in listed and t not in {"user_roles", "user_segments", "audit_events"}}
    assert missing == set(), missing


@pytest.mark.parametrize("action", ["dsr.reject", "dsr.fail"])
def test_d_inv4_reject_and_fail_require_reason(action):
    for t in TRANSITIONS:
        if t["action"] == action:
            assert "reason_code_required" in t["guards"], t
    assert POLICY["reject_reason_codes"] and POLICY["fail_reason_codes"]


def test_d_inv5_officer_never_decides_own_request():
    for t in TRANSITIONS:
        if t["action"] in {"dsr.verify", "dsr.reject"}:
            assert t["actors"] == ["privacy_officer"] and "not_requester" in t["guards"], t


def test_d_inv6_terminal_states_have_no_outgoing_transitions():
    assert TERMINAL == {"rejected", "cancelled", "expired", "closed"}
    assert [t for t in TRANSITIONS if t["from"] in TERMINAL] == []


def test_requester_cannot_cancel_once_processing_started():
    for t in TRANSITIONS:
        if t["action"] == "dsr.cancel":
            assert t["from"] in {"pending_verification", "received"}, t


def test_d_inv7_every_transition_has_a_privacy_audit_action():
    for t in TRANSITIONS:
        assert t["audit"].startswith("privacy.dsr."), t
    assert "privacy.export.request" in AUDIT and "privacy.deletion.request" in AUDIT


def test_d_inv8_retained_categories_are_anonymized_not_deleted():
    retained = {c["category"]: c["erasure"] for c in POLICY["data_categories"]}
    for category in ("audit", "consents", "ai_usage", "deletion_requests"):
        assert retained[category] == "retain_anonymized", category
    assert retained["documents"] == "delete_with_storage_objects"


def test_d_inv9_download_is_single_use_and_short_lived():
    limits = POLICY["limits"]
    assert limits["export_download_uses"] == 1 and limits["export_download_ttl_hours"] == 24
    assert limits["open_requests_per_type"] == 1
    expire = [t for t in TRANSITIONS if t["to"] == "expired"]
    assert expire and all("export_only" in t["guards"] for t in expire)


def test_failed_retry_is_bounded():
    (retry,) = [t for t in TRANSITIONS if t["action"] == "dsr.retry"]
    assert "attempts_below_max" in retry["guards"] and POLICY["limits"]["max_attempts"] == 3


def test_document_matches_json():
    for code in POLICY["request_types"]:
        assert f"`{code}`" in DOC, code
    for state in STATES:
        assert f"`{state}`" in DOC, state
    for code in POLICY["reject_reason_codes"] + POLICY["fail_reason_codes"]:
        assert f"`{code}`" in DOC, code
    for col in POLICY["never_export_columns"]:
        assert f"`{col}`" in DOC, col
    for invariant in POLICY["invariants"]:
        key, text = invariant.split(" ", 1)
        assert f"**{key}** {text}" in DOC, key
    assert "10분" in DOC and "24시간" in DOC and "PROPOSED" in DOC
