"""T81 contract readiness checks (documents and proposal only — no API/DB code).

- Merges docs/admin/t81_openapi_proposal.yaml into docs/api/openapi.yaml **in memory** and runs the project's own
  checker (docs/api/check_openapi.py: OpenAPI 3.1 validation, $ref, examples, contract rules, traceability).
  Only for that run, the proposed T04/T05 IDs (FR-ADM-007, UI-027, moderation tables) are added to the checker.
- Compares the proposal with the T82 hand-written TypeScript types and HTTP adapter.
- Cross-checks enums and error codes with the T80 documents and the backend error catalog.

    python -B -m unittest docs/admin/test_t81_contract_readiness.py -v
Needs pyyaml, jsonschema, openapi-spec-validator (same as docs/api/check_openapi.py); skips otherwise.
"""
from __future__ import annotations

import copy
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT / "docs/admin"
READINESS = (ADMIN / "T81_IMPLEMENTATION_READINESS.md").read_text(encoding="utf-8")
DIAGRAM = (ADMIN / "MODERATION_STATE_DIAGRAM.md").read_text(encoding="utf-8")
POLICY = (ADMIN / "MODERATION_POLICY.md").read_text(encoding="utf-8")
CONTRACT = (ADMIN / "MODERATION_IMPLEMENTATION_CONTRACT.md").read_text(encoding="utf-8")
FRONT_TYPES = (ROOT / "frontend/src/api/moderation.ts").read_text(encoding="utf-8")
FRONT_HTTP = (ROOT / "frontend/src/api/moderationHttp.ts").read_text(encoding="utf-8")

try:
    import yaml  # noqa: F401
    import jsonschema  # noqa: F401
    import openapi_spec_validator  # noqa: F401
    DEPS = True
except ImportError:  # pragma: no cover
    DEPS = False

PROPOSED_REQUIREMENTS = {"FR-ADM-007"}
PROPOSED_SCREENS = {"UI-027"}
PROPOSED_TABLES = {"moderation_cases", "moderation_case_events"}


def load_checker():
    spec = importlib.util.spec_from_file_location("check_openapi", ROOT / "docs/api/check_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ts_fields(interface: str) -> set[str]:
    body = re.search(rf"export interface {interface}[^{{]*\{{(.*?)\n\}}", FRONT_TYPES, re.S).group(1)
    return set(re.findall(r"^\s+(\w+)\??:", body, re.M))


@unittest.skipUnless(DEPS, "needs pyyaml, jsonschema, openapi-spec-validator")
class OpenApiProposalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml
        cls.base = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
        cls.proposal = yaml.safe_load((ADMIN / "t81_openapi_proposal.yaml").read_text(encoding="utf-8"))
        cls.merged = copy.deepcopy(cls.base)
        cls.merged["paths"].update(cls.proposal["paths"])
        cls.merged["components"]["schemas"].update(cls.proposal["components"]["schemas"])
        cls.schemas = cls.proposal["components"]["schemas"]

    def test_proposal_is_not_in_the_real_contract(self):
        for path in self.proposal["paths"]:
            self.assertNotIn(path, self.base["paths"])
        for name in self.schemas:
            self.assertNotIn(name, self.base["components"]["schemas"])

    def test_merged_spec_passes_the_project_checker_with_the_proposed_t04_t05_ids(self):
        from openapi_spec_validator import validate as validate_spec
        checker = load_checker()
        validate_spec(self.merged)
        original_ids, original_tables = checker.load_ids, checker.load_tables

        def ids(root):
            fr, all_ids, screens = original_ids(root)
            return fr | PROPOSED_REQUIREMENTS, all_ids | PROPOSED_REQUIREMENTS, screens | PROPOSED_SCREENS

        checker.load_ids = ids
        checker.load_tables = lambda: original_tables() | PROPOSED_TABLES
        try:
            errors, stats = checker.check(self.merged, ROOT / "docs/requirements")
        finally:
            checker.load_ids, checker.load_tables = original_ids, original_tables
        self.assertEqual(errors, [])
        self.assertEqual(stats["operations"], len(list(checker.operations(self.base))) + 4)

    def test_without_the_t04_t05_changes_the_proposal_is_rejected(self):
        checker = load_checker()
        errors, _ = checker.check(self.merged, ROOT / "docs/requirements")
        self.assertTrue(any("FR-ADM-007" in e for e in errors), "proves the T04 change is required")
        self.assertTrue(any("moderation_cases" in e for e in errors), "proves the T05 change is required")

    def test_reuses_existing_pagination_and_error_components(self):
        list_op = self.proposal["paths"]["/admin/moderation-cases"]["get"]
        refs = [p.get("$ref") for p in list_op["parameters"]]
        self.assertIn("#/components/parameters/Limit", refs)
        self.assertIn("#/components/parameters/Cursor", refs)
        self.assertEqual(list_op["responses"]["400"]["$ref"], "#/components/responses/BadCursor")
        self.assertEqual(self.schemas["ModerationCasePage"]["properties"]["next_cursor"]["$ref"],
                         "#/components/schemas/NextCursor")
        for path, item in self.proposal["paths"].items():
            for op in item.values():
                self.assertEqual(op["tags"], ["admin"], path)
                self.assertIn("403", op["responses"])

    def test_enums_match_the_t80_documents(self):
        states = {r.split("|")[1].strip() for r in DIAGRAM.split("## 2. 상태", 1)[1].split("## 3.", 1)[0].splitlines()
                  if re.match(r"^\| [A-Z_]+ \|", r)}
        self.assertEqual(set(self.schemas["ModerationStatus"]["enum"]), states)
        reasons = set(re.findall(r"^\| `([A-Z_]+)` \|", POLICY.split("### 5.1", 1)[1].split("### 5.2", 1)[0], re.M))
        self.assertEqual(set(self.schemas["ModerationReasonCode"]["enum"]), reasons)
        targets = set(re.findall(r"^\| `([a-z_]+)` \|", CONTRACT.split("## 1. 검수 대상 유형", 1)[1].split("## 2.", 1)[0], re.M))
        self.assertEqual(set(self.schemas["ModerationTargetType"]["enum"]), targets - {"target_type"})
        self.assertIn("review_trigger IN ('PRE_PUBLISH', 'REPORT', 'EXPIRY', 'SOURCE_CHANGE')", CONTRACT)
        self.assertEqual(self.schemas["ModerationTrigger"]["enum"], ["PRE_PUBLISH", "REPORT", "EXPIRY", "SOURCE_CHANGE"])

    def test_note_is_request_only(self):
        self.assertIn("note", self.schemas["ModerationDecisionRequest"]["properties"])
        for name in ("ModerationCaseSummary", "ModerationCaseDetail", "ModerationCaseEvent"):
            props = self.schemas[name]["properties"]
            self.assertFalse({"note", "reviewer_note", "reporter_id"} & set(props), name)

    def test_detail_contains_every_summary_field(self):
        summary = set(self.schemas["ModerationCaseSummary"]["properties"])
        detail = set(self.schemas["ModerationCaseDetail"]["properties"])
        self.assertLessEqual(summary, detail)
        self.assertEqual(set(self.schemas["ModerationCaseDetail"]["required"]), detail)

    def test_t82_type_differences_are_exactly_the_documented_ones(self):
        summary = set(self.schemas["ModerationCaseSummary"]["properties"])
        detail = set(self.schemas["ModerationCaseDetail"]["properties"])
        event = set(self.schemas["ModerationCaseEvent"]["properties"])
        self.assertEqual(summary - ts_fields("ModerationCaseSummary"), {"overdue", "created_at"})
        self.assertEqual(ts_fields("ModerationCaseSummary") - summary, set())
        self.assertEqual((ts_fields("ModerationCaseDetail") | ts_fields("ModerationCaseSummary")) - detail, set())
        self.assertEqual(event - ts_fields("ModerationCaseEvent"), {"actor_user_id"})
        self.assertEqual(ts_fields("ModerationCaseEvent") - event, {"actor_id"})
        self.assertIn("`actor_id` | **`actor_user_id`**", READINESS)

    def test_t82_adapter_paths_match_the_proposal(self):
        self.assertIn("const BASE = '/v1/admin/moderation-cases';", FRONT_HTTP)
        for suffix in ("/assignment", "/decision"):
            self.assertIn(suffix, FRONT_HTTP)
            self.assertIn(f"/admin/moderation-cases/{{case_id}}{suffix}", self.proposal["paths"])


class RepositoryFactsTest(unittest.TestCase):
    def test_cited_error_codes_exist(self):
        catalog = (ROOT / "backend/app/core/errors.py").read_text(encoding="utf-8")
        existing = set(re.findall(r'^\s+([A-Z_]+) = "', catalog, re.M))
        cited = set(re.findall(r"\b(?:400|401|403|404|409|422|503) `([A-Z_]+)`", READINESS))
        cited |= {"INVALID_CURSOR", "CONFLICT", "APPROVAL_CLOSED", "VALIDATION_FAILED", "FORBIDDEN"}
        self.assertLessEqual(cited, existing)

    def test_permission_is_still_only_proposed_and_the_guard_exists(self):
        seed = (ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8")
        self.assertNotIn("admin.content.review", seed)
        auth = (ROOT / "backend/app/dependencies/auth.py").read_text(encoding="utf-8")
        self.assertIn("def require_permissions(", auth)

    def test_moderation_implementation_is_one_migration_behind_a_default_off_flag(self):
        # T81 구현(0010 + ADMIN_MODERATION_API, 기본 꺼짐). 계약 DDL 스케치 외 대상은 company_posting(0009) 하나만 추가.
        found = [p.name for p in (ROOT / "database/migrations").glob("*.sql")
                 if "CREATE TABLE career.moderation_cases" in p.read_text(encoding="utf-8")]
        self.assertEqual(found, ["0010_moderation_cases.sql"])
        self.assertFalse((ROOT / "database/migrations/0004_moderation_cases.sql").exists())
        config = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
        self.assertIn('admin_moderation_api=os.environ.get("ADMIN_MODERATION_API", "false")', config)
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        self.assertIn("if settings.admin_moderation_api:", main)

    def test_f027_is_still_excluded_in_the_source_of_truth(self):
        trace = (ROOT / "docs/requirements/traceability/TRACEABILITY.md").read_text(encoding="utf-8")
        self.assertIn("| F-027 | 운영 콘텐츠 검수 | **제외**", trace)
        self.assertNotIn("FR-ADM-007", (ROOT / "docs/requirements/functional/ADMIN.md").read_text(encoding="utf-8"))

    def test_document_worker_cascade_fact_cited_in_trigger_comparison(self):
        worker = (ROOT / "backend/app/document_worker.py").read_text(encoding="utf-8")
        self.assertIn("CASCADE", worker)
        self.assertIn("backend/app/document_worker.py", READINESS)

    def test_every_transition_is_mapped_to_an_api_or_deferred(self):
        section = READINESS.split("## 7. 권한·상태 전이 ↔ API", 1)[1].split("## 8.", 1)[0]
        mapped = re.findall(r"^\| (T\d\d) ", section, re.M)
        self.assertEqual(mapped, [f"T{i:02d}" for i in range(1, 14)])
        table_ids = re.findall(r"^\| (T\d\d) \|", DIAGRAM, re.M)
        self.assertEqual(sorted(set(table_ids)), mapped)

    def test_readiness_is_marked_unapproved(self):
        self.assertIn("**PROPOSED / 미승인", READINESS)
        self.assertIn("T81 실제 구현 착수는 **HOLD**", READINESS)
        self.assertNotRegex(READINESS, r"(정책|범위) 승인: 완료")


if __name__ == "__main__":
    unittest.main()
