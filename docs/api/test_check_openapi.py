"""T06: tests for docs/api/check_openapi.py.

Run: python3 -B -m unittest docs/api/test_check_openapi.py -v
Needs docs/requirements (T04) and database/DATA_DICTIONARY.md (T05) in the tree,
or T06_REQUIREMENTS_ROOT pointing at a docs/requirements directory.
"""
import copy
import os
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_openapi as co  # noqa: E402

REQ_ROOT = Path(os.environ.get("T06_REQUIREMENTS_ROOT", co.ROOT / "docs" / "requirements"))
SPEC = yaml.safe_load(co.SPEC.read_text(encoding="utf-8"))


def errors(spec):
    return co.check(spec, REQ_ROOT)[0]


class OpenApiContractTest(unittest.TestCase):
    def test_current_spec_passes(self):
        co.validate_spec(SPEC)
        self.assertEqual(errors(SPEC), [])

    def test_bad_example_is_caught(self):
        spec = copy.deepcopy(SPEC)
        ex = spec["paths"]["/matches"]["post"]["responses"]["201"]["content"]["application/json"]["example"]
        ex["score"] = 140  # above 100
        self.assertTrue(any("example invalid" in e for e in errors(spec)))

    def test_probability_flag_must_be_false(self):
        spec = copy.deepcopy(SPEC)
        ex = spec["paths"]["/matches"]["post"]["responses"]["201"]["content"]["application/json"]["example"]
        ex["score_is_probability"] = True
        self.assertTrue(any("example invalid" in e for e in errors(spec)))

    def test_protected_operation_needs_401(self):
        spec = copy.deepcopy(SPEC)
        del spec["paths"]["/me"]["get"]["responses"]["401"]
        self.assertTrue(any("protected operation without 401" in e for e in errors(spec)))

    def test_me_must_not_take_user_id(self):
        spec = copy.deepcopy(SPEC)
        spec["paths"]["/me"]["get"].setdefault("parameters", []).append(
            {"name": "user_id", "in": "query", "schema": {"type": "string"}}
        )
        self.assertTrue(any("must not take user_id" in e for e in errors(spec)))

    def test_unknown_table_is_caught(self):
        spec = copy.deepcopy(SPEC)
        spec["paths"]["/me"]["get"]["x-tables"].append("userz")
        self.assertTrue(any("unknown table" in e for e in errors(spec)))

    def test_requirement_coverage_is_enforced(self):
        spec = copy.deepcopy(SPEC)
        for item in spec["paths"].values():
            for op in item.values():
                if isinstance(op, dict) and "x-requirements" in op:
                    op["x-requirements"] = [r for r in op["x-requirements"] if r != "FR-JOB-007"] or ["FR-JOB-001"]
        self.assertTrue(any("FR-JOB-007" in e for e in errors(spec)))

    def test_errors_must_use_error_response(self):
        spec = copy.deepcopy(SPEC)
        content = spec["paths"]["/auth/login"]["post"]["responses"]["401"]["content"]
        content["application/problem+json"] = content.pop("application/json")
        self.assertTrue(any("ErrorResponse" in e for e in errors(spec)))

    def test_error_schema_must_be_error_response(self):
        spec = copy.deepcopy(SPEC)
        content = spec["paths"]["/auth/login"]["post"]["responses"]["401"]["content"]["application/json"]
        content["schema"] = {"type": "object"}
        self.assertTrue(any("ErrorResponse" in e for e in errors(spec)))

if __name__ == "__main__":
    unittest.main()
