"""T84 contract readiness checks (documents and proposal only — no API/DB code).

- Replaces the two existing operations in docs/api/openapi.yaml with docs/security/t84_openapi_proposal.yaml
  **in memory** and runs the project's own checker (docs/api/check_openapi.py). No ID patching is needed:
  FR-ADM-004/005, UI-028, audit_events and ai_usage_records already exist in T04/T05.
- Cross-checks every filter, sort key and response field with the real 0001 DDL, the permission with the
  seed and the auth guard, and every cited error code with the backend error catalog.
- Proves the documented differences from the confirmed contract are exactly the ones in the proposal.

    python -B -m unittest docs/security/test_t84_contract_readiness.py -v
Needs pyyaml, jsonschema, openapi-spec-validator (same as docs/api/check_openapi.py); skips otherwise.
"""
from __future__ import annotations

import copy
import importlib.util
import re
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEC = ROOT / "docs/security"
READINESS = (SEC / "T84_AUDIT_USAGE_API_READINESS.md").read_text(encoding="utf-8")
DDL = (ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8")
SEED = (ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8")
ERRORS = (ROOT / "backend/app/core/errors.py").read_text(encoding="utf-8")
T83 = (SEC / "AUDIT_EVENT_CONTRACT.md").read_text(encoding="utf-8")

try:
    import yaml  # noqa: F401
    import jsonschema  # noqa: F401
    import openapi_spec_validator  # noqa: F401
    DEPS = True
except ImportError:  # pragma: no cover
    DEPS = False

AUDIT, USAGE = "/admin/audit-events", "/admin/ai-usage"
T83_ONLY_COLUMNS = {"audit_seq", "recorded_at", "actor_type", "result", "reason_code", "client_ip_hash",
                    "changed_fields", "metadata", "retention_class", "retain_until", "row_hash"}
MASKED_RESOURCE_TYPES = {"user"}  # D3 (PROPOSED)


def load_checker():
    spec = importlib.util.spec_from_file_location("check_openapi", ROOT / "docs/api/check_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_columns(table: str) -> dict[str, str]:
    body = re.search(rf"CREATE TABLE career\.{table} \((.*?)\n\);", DDL, re.S).group(1)
    cols = {}
    for line in body.splitlines():
        m = re.match(r"^\s+([a-z_]+) ([a-z]+(?:\(\d+(?:,\d+)?\))?)(.*)$", line)
        if m and m.group(1) not in {"primary", "check"}:
            cols[m.group(1)] = (m.group(2) + m.group(3)).rstrip(",")
    return cols


def table_indexes(table: str) -> list[str]:
    return re.findall(rf"CREATE INDEX \w+ ON career\.{table} \(([^)]*)\);", DDL)


def mask_uuid(value: uuid.UUID) -> str:
    """Reference implementation of §7 (8 head + 4 tail hex, UUID shape kept)."""
    h = value.hex
    return f"{h[:8]}-****-****-****-********{h[-4:]}"


@unittest.skipUnless(DEPS, "needs pyyaml, jsonschema, openapi-spec-validator")
class OpenApiProposalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml
        cls.base = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
        cls.proposal = yaml.safe_load((SEC / "t84_openapi_proposal.yaml").read_text(encoding="utf-8"))
        cls.merged = cls.merge(cls.proposal)
        cls.schemas = cls.proposal["components"]["schemas"]
        cls.audit = cls.proposal["paths"][AUDIT]["get"]
        cls.usage = cls.proposal["paths"][USAGE]["get"]

    @classmethod
    def merge(cls, proposal):
        merged = copy.deepcopy(cls.base)
        merged["paths"].update(copy.deepcopy(proposal["paths"]))
        merged["components"]["schemas"].update(copy.deepcopy(proposal["components"]["schemas"]))
        return merged

    def run_checker(self, spec):
        from openapi_spec_validator import validate as validate_spec
        validate_spec(spec)
        return load_checker().check(spec, ROOT / "docs/requirements")

    # --- relation to the confirmed contract -------------------------------------------------------
    def test_replaces_existing_operations_only_and_keeps_paths_and_operation_ids(self):
        self.assertEqual(set(self.proposal["paths"]), {AUDIT, USAGE})
        for path, item in self.proposal["paths"].items():
            self.assertIn(path, self.base["paths"], "T84 must not invent a new path")
            self.assertEqual(item["get"]["operationId"], self.base["paths"][path]["get"]["operationId"])
        self.assertNotIn("/admin/audit", self.base["paths"])
        self.assertNotIn("/admin/audit", self.proposal["paths"])
        for name in self.schemas:
            self.assertNotIn(name, self.base["components"]["schemas"], "new schema names only")

    def test_merged_spec_passes_the_project_checker_without_any_id_patching(self):
        errors, stats = self.run_checker(self.merged)
        self.assertEqual(errors, [])
        self.assertEqual(stats["operations"], len(list(load_checker().operations(self.base))))

    def test_checker_still_rejects_broken_variants_of_the_proposal(self):
        from openapi_spec_validator import validate as validate_spec
        broken = copy.deepcopy(self.proposal)
        broken["paths"][AUDIT]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] = \
            "#/components/schemas/DoesNotExist"
        with self.assertRaises(Exception):
            validate_spec(self.merge(broken))
        broken = copy.deepcopy(self.proposal)
        del broken["paths"][USAGE]["get"]["responses"]["401"]
        errors, _ = load_checker().check(self.merge(broken), ROOT / "docs/requirements")
        self.assertTrue(any("without 401" in e for e in errors))
        broken = copy.deepcopy(self.proposal)
        broken["paths"][AUDIT]["get"]["x-tables"] = ["audit_log"]
        errors, _ = load_checker().check(self.merge(broken), ROOT / "docs/requirements")
        self.assertTrue(any("unknown table" in e for e in errors))

    def test_differences_from_the_confirmed_contract_are_exactly_the_documented_ones(self):
        def names(op):
            return {p.get("name") or p["$ref"].rsplit("/", 1)[1] for p in op["parameters"]}
        base_audit, base_usage = self.base["paths"][AUDIT]["get"], self.base["paths"][USAGE]["get"]
        self.assertEqual(names(self.audit) - names(base_audit), {"resource_type", "request_id"})
        self.assertEqual(names(base_audit) - names(self.audit), set())
        self.assertEqual(set(self.audit["responses"]) - set(base_audit["responses"]), {"400", "429", "503"})
        self.assertEqual(names(self.usage), names(base_usage))
        self.assertEqual(set(self.usage["responses"]) - set(base_usage["responses"]), {"429"})
        self.assertEqual(set(base_usage["x-tables"]) - set(self.usage["x-tables"]), {"model_versions"})
        section = READINESS.split("## 12.", 1)[1].split("## 13.", 1)[0]
        for token in ("resource_type", "request_id", "400", "429", "503", "model_versions",
                      "actor_user_id_masked", "AiUsageReport", "unpriced_request_count"):
            self.assertIn(token, section)

    def test_reuses_existing_pagination_and_error_components(self):
        refs = [p.get("$ref") for p in self.audit["parameters"]]
        self.assertIn("#/components/parameters/Limit", refs)
        self.assertIn("#/components/parameters/Cursor", refs)
        self.assertEqual(self.base["components"]["parameters"]["Limit"]["schema"]["maximum"], 100)
        self.assertEqual(self.schemas["AuditEventViewPage"]["properties"]["items"]["maxItems"], 100)
        self.assertEqual(self.audit["responses"]["400"]["$ref"], "#/components/responses/BadCursor")
        self.assertEqual(self.schemas["AuditEventViewPage"]["properties"]["next_cursor"]["$ref"],
                         "#/components/schemas/NextCursor")
        for op in (self.audit, self.usage):
            self.assertEqual(op["tags"], ["admin"])
            self.assertIn("403", op["responses"])

    # --- database model (0001) --------------------------------------------------------------------
    def test_audit_filters_sort_keys_and_fields_exist_in_the_0001_table(self):
        cols = table_columns("audit_events")
        self.assertEqual(set(cols), {"audit_event_id", "actor_user_id", "action_code", "resource_type",
                                     "resource_id", "request_id", "occurred_at"})
        filters = {p["name"] for p in self.audit["parameters"] if "name" in p} - {"from", "to"}
        self.assertLessEqual(filters, set(cols))
        fields = {f.removesuffix("_masked") for f in self.schemas["AuditEventView"]["properties"]}
        self.assertLessEqual(fields - {"resource_id"}, set(cols))
        self.assertIn("occurred_at DESC", table_indexes("audit_events"))
        self.assertIn("(occurred_at, audit_event_id)", READINESS)
        for name, schema in (("action_code", "varchar(100)"), ("resource_type", "varchar(80)"),
                             ("request_id", "varchar(64)")):
            self.assertTrue(cols[name].startswith(schema))
            param = next(p for p in self.audit["parameters"] if p.get("name") == name)
            self.assertEqual(param["schema"]["maxLength"], int(re.search(r"\d+", schema).group()))

    def test_no_t83_only_column_is_used_by_the_proposal(self):
        text = (SEC / "t84_openapi_proposal.yaml").read_text(encoding="utf-8")
        used = set(self.schemas["AuditEventView"]["properties"]) | {
            p.get("name") for p in self.audit["parameters"]}
        self.assertEqual(used & T83_ONLY_COLUMNS, set())
        self.assertEqual(T83_ONLY_COLUMNS & set(table_columns("audit_events")), set(), "still not migrated")
        for col in T83_ONLY_COLUMNS - {"result", "metadata"}:
            self.assertNotIn(f"{col}:", text)

    def test_usage_groups_and_amounts_map_to_0001_columns(self):
        cols = table_columns("ai_usage_records")
        groups = next(p for p in self.usage["parameters"] if p["name"] == "group_by")["schema"]["enum"]
        self.assertLessEqual(set(groups) - {"day"}, set(cols))
        self.assertIn("occurred_at", cols)
        amounts = set(self.schemas["AiUsageAmounts"]["properties"])
        self.assertLessEqual(amounts - {"request_count", "unpriced_request_count"}, set(cols))
        features = re.search(r"CHECK \(feature_code IN \(([^)]*)\)\)", DDL).group(1)
        self.assertEqual(re.findall(r"'([a-z_]+)'", features), ["document_analysis", "rag_answer", "agent"])
        self.assertNotIn("user_id", amounts | set(groups), "no per-user breakdown")

    def test_cost_blocker_is_a_real_0001_fact_and_unknown_cost_is_never_zero(self):
        cost = table_columns("ai_usage_records")["estimated_cost_usd"]
        self.assertIn("NOT NULL DEFAULT 0", cost, "D2 blocker: unrecorded cost is indistinguishable from 0")
        self.assertIn("NOT NULL DEFAULT 0", READINESS)
        for name in ("AiUsageAmounts", "AiUsageReportBucket"):
            self.assertEqual(self.schemas[name]["properties"]["estimated_cost_usd"]["type"], ["number", "null"])
        example = self.usage["responses"]["200"]["content"]["application/json"]["example"]
        self.assertEqual(example["buckets"], [], "no invented usage numbers in the contract")
        self.assertIsNone(example["totals"]["estimated_cost_usd"])
        self.assertTrue(self.schemas["AiUsageReport"]["properties"]["cost_is_estimate"]["const"])

    # --- masking ----------------------------------------------------------------------------------
    def test_masking_pattern_matches_the_reference_mask_and_rejects_raw_ids(self):
        pattern = re.compile(self.schemas["MaskedUuid"]["pattern"])
        sample = uuid.UUID("0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0")
        self.assertRegex(mask_uuid(sample), pattern)
        self.assertEqual(len(mask_uuid(sample)), 36)
        self.assertNotRegex(str(sample), pattern)
        props = self.schemas["AuditEventView"]["properties"]
        self.assertNotIn("actor_user_id", props, "raw actor id is never returned")
        self.assertEqual({"user_id", "email", "name", "client_ip", "metadata"} & set(props), set())
        for item in self.audit["responses"]["200"]["content"]["application/json"]["example"]["items"]:
            self.assertEqual(item["resource_id_masked"], item["resource_type"] in MASKED_RESOURCE_TYPES)

    # --- permissions ------------------------------------------------------------------------------
    def test_permission_reuses_the_seeded_admin_audit_read(self):
        for op in (self.audit, self.usage):
            self.assertEqual(op["x-t84-permission"], "admin.audit.read")
            self.assertEqual(op["x-t84-status"], "PROPOSED")
        self.assertIn("('admin.audit.read', '감사 기록 조회')", SEED)
        self.assertRegex(SEED, r"r\.code = 'admin' AND p\.code IN \([^)]*'admin\.audit\.read'")
        auth = (ROOT / "backend/app/dependencies/auth.py").read_text(encoding="utf-8")
        self.assertIn("def require_permissions(", auth)
        self.assertIn("def require_roles(", auth)
        self.assertNotIn("admin.ai_usage.read", SEED, "no new permission code is created by T84")


class RepositoryFactsTest(unittest.TestCase):
    def test_cited_error_codes_exist_in_the_backend_catalog(self):
        existing = set(re.findall(r'^\s+([A-Z_]+) = "', ERRORS, re.M))
        cited = set(re.findall(r"\b(?:400|401|403|404|409|422|429|503) `([A-Z_]+)`", READINESS))
        self.assertGreaterEqual(len(cited), 6)
        self.assertLessEqual(cited, existing)

    def test_no_t84_api_code_or_migration_exists_yet(self):
        for path in (ROOT / "backend/app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("audit-events", text, path)
            self.assertNotIn("ai-usage", text, path)
        self.assertEqual(sorted(p.name[:4] for p in (ROOT / "database/migrations").glob("[0-9]*.sql")),
                         ["0001", "0002", "0003"])

    def test_no_backend_writer_for_ai_usage_records_yet(self):
        writers = [p for p in (ROOT / "backend/app").rglob("*.py")
                   if re.search(r"INSERT INTO\s+career\.ai_usage_records", p.read_text(encoding="utf-8"))]
        self.assertEqual(writers, [])
        repo = (ROOT / "backend/app/repositories/document_analyses.py").read_text(encoding="utf-8")
        self.assertIn("ai_usage_records is intentionally NOT written", repo)

    def test_t83_contract_is_still_draft_and_its_read_audit_proposal_is_cited(self):
        self.assertIn("DRAFT / NOT APPROVED / NOT MIGRATED", T83)
        self.assertIn("`admin.audit.view`", T83)
        self.assertIn("최대 90일", T83)
        self.assertIn("admin.audit.view", READINESS)

    def test_d2_historical_zero_cost_is_not_treated_as_free_and_no_bulk_update(self):
        section = READINESS.split("## 10.", 1)[1].split("## 11.", 1)[0]
        self.assertIn("실제 무료 사용으로 단정하지 않습니다", section)
        self.assertIn("일괄 `NULL`로 바꾸는 UPDATE는 하지 않습니다", section)
        self.assertIn("별도 Migration 승인 후에만", section)

    def test_d4_processing_order_and_self_event_exclusion(self):
        section = READINESS.split("## 11.", 1)[1].split("## 12.", 1)[0]
        steps = re.findall(r"^\| (\d) \| ([^|]+)\|", section, re.M)
        self.assertEqual([n for n, _ in steps], ["1", "2", "3", "4", "5", "6"])
        for (_, text), word in zip(steps, ("권한", "검증", "범위 확정", "INSERT", "성공 확인", "SELECT")):
            self.assertIn(word, text)
        self.assertIn("자기 조회 이벤트는 그 응답에 포함하지 않습니다", section)
        self.assertIn("audit_event_id <> :self", section)
        self.assertIn("min(to, as_of)", section)
        self.assertIn("PM 승인 전까지 PROPOSED", section)

    def test_implementation_plan_has_18_steps(self):
        section = READINESS.split("## 14.", 1)[1].split("## 15.", 1)[0]
        self.assertEqual(re.findall(r"^\| (\d+) \|", section, re.M), [str(i) for i in range(1, 19)])

    def test_readiness_is_marked_unapproved_and_implementation_on_hold(self):
        self.assertIn("**PROPOSED / 미승인", READINESS)
        self.assertIn("T84 실제 API 구현 착수는 **HOLD**", READINESS)
        self.assertNotRegex(READINESS, r"(정책|계약|스키마) 승인: 완료")


if __name__ == "__main__":
    unittest.main()
