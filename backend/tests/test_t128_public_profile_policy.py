"""T128 공개 프로필 동의 정책(PROPOSED) — 비공개 기본·공개 불가 항목·노출 경로·철회·스키마 일치 시험."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "docs" / "enterprise" / "t128_public_profile_fields.json").read_text(encoding="utf-8"))
MATRIX = json.loads((ROOT / "docs" / "enterprise" / "t121_role_matrix.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "enterprise" / "T128_PUBLIC_PROFILE_CONSENT_POLICY.md").read_text(encoding="utf-8")
SCHEMA = (ROOT / "database" / "migrations" / "0001_initial_schema.sql").read_text(encoding="utf-8")
FIELDS = {f["key"]: f for f in POLICY["fields"]}
NEVER = {"email", "documents", "analysis_results", "job_applications", "behavior_events", "consents_and_account"}


def table_columns(table: str) -> set[str]:
    match = re.search(rf"CREATE TABLE career\.{table} \((.*?)\n\);", SCHEMA, re.S)
    assert match, table
    return {line.split()[0] for line in match.group(1).splitlines() if line.strip() and line.startswith("    ")
            and not line.strip().startswith(("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"))}


def test_policy_is_proposed_and_requires_consent():
    assert POLICY["status"] == "PROPOSED"
    assert POLICY["consent_required"] is True and POLICY["consent_policy_code"] == "public_profile"


def test_pp_inv1_every_field_defaults_to_private():
    assert POLICY["default_visibility"] == "private"
    assert {f["default"] for f in POLICY["fields"]} == {"private"}


@pytest.mark.parametrize("key", sorted(NEVER))
def test_pp_inv2_sensitive_groups_can_never_be_published(key):
    assert FIELDS[key]["publishable"] is False and FIELDS[key]["risk"] == "high"


def test_only_low_or_medium_risk_fields_are_publishable():
    for f in POLICY["fields"]:
        if f["publishable"]:
            assert f["risk"] in {"low", "medium"}, f["key"]


def test_publishable_fields_point_at_real_schema_columns():
    """정책이 존재하지 않는 열을 가리키면(오타·스키마 변경) 실패."""
    for f in POLICY["fields"]:
        if not f["publishable"]:
            continue
        table, _, cols = f["source"].partition(".")
        columns = table_columns(table)
        for col in cols.split(","):
            assert col in columns, (f["key"], table, col)


def test_pp_inv3_revocation_is_immediate_and_resets_selection():
    rev = POLICY["revocation"]
    assert rev["effect"] == "immediate" and rev["per_link_revoke"] is True
    assert "모든 링크 무효" in rev["scope"] and "비공개" in rev["scope"]


def test_pp_inv4_no_search_index_no_company_search_no_listing():
    exp = POLICY["exposure"]
    assert exp["search_engine_indexing"] is False and exp["company_search"] is False
    assert exp["listing_or_directory"] is False and exp["access"] == "share_link_only"
    assert "noindex" in exp["robots"] and exp["cache_control"] == "no-store" and exp["referrer_policy"] == "no-referrer"
    # T121: 후보자 검색은 모든 역할 거부, 공개 프로필은 '동의 범위'만
    actions = {a["action"]: a["decisions"] for a in MATRIX["actions"]}
    assert set(actions["candidate.search"].values()) == {"deny"}
    assert set(actions["candidate.view_public_profile"].values()) == {"consented"}


def test_pp_inv5_link_rules():
    links = POLICY["links"]
    assert links["token_min_entropy_bits"] >= 128
    assert links["default_ttl_days"] <= links["max_ttl_days"] <= 90
    assert 1 <= links["max_active_links"] <= 3
    assert links["revoked_or_expired_response"].startswith("404")


def test_pp_inv6_live_rendering_and_new_items_private():
    prop = POLICY["deletion_propagation"]
    assert "CASCADE" in prop["account_deletion"] and "즉시" in prop["item_deletion"]
    assert "비공개" in prop["new_items"]
    for key in ("experience.organization", "project.title"):
        assert FIELDS[key]["granularity"] == "item"


def test_document_lists_every_field_invariant_and_url_risk():
    for key in FIELDS:
        assert f"`{key}`" in DOC, key
    for invariant in POLICY["invariants"]:
        assert invariant.split(" ", 1)[0] in DOC
    for risk in ("재배포", "캡처", "추측", "검색 노출", "캐시", "Referer", "접근 로그"):
        assert risk in DOC, risk
    assert "법무" in DOC
