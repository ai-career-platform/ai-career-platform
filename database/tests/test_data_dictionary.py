"""T05: unit tests for database/model/check_data_dictionary.py (no database needed).

Run: python3 -B -m unittest discover -s database/tests -p "test_data_dictionary.py" -v
Requirement-coverage tests need docs/requirements (T04) or T05_REQUIREMENTS_DIR.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "database" / "model"))
import check_data_dictionary as cdd  # noqa: E402

import os

TEXT = cdd.DICTIONARY.read_text(encoding="utf-8")
REQ_DIR = Path(os.environ.get("T05_REQUIREMENTS_DIR", cdd.REQUIREMENTS_DIR))
REQ_IDS = cdd.load_requirement_ids(REQ_DIR)


def errors_for(text):
    return cdd.validate(cdd.parse(text), REQ_IDS)


class DataDictionaryTest(unittest.TestCase):
    def test_current_dictionary_is_valid(self):
        self.assertEqual(errors_for(TEXT), [])

    @unittest.skipIf(REQ_IDS is None, "docs/requirements (T04) not in tree")
    def test_every_functional_requirement_maps_to_a_table(self):
        mapped = set().union(*(t.features for t in cdd.parse(TEXT)))
        functional = {r for r in REQ_IDS if r.startswith("FR-")}
        self.assertEqual(functional - mapped, set(cdd.NO_DATA_REQUIREMENTS))

    def test_ddl_orders_referenced_tables_first(self):
        ddl = cdd.ddl(cdd.parse(TEXT))
        self.assertLess(ddl.index("CREATE TABLE users ("), ddl.index("CREATE TABLE user_profiles ("))
        self.assertLess(ddl.index("CREATE TABLE consent_policies ("), ddl.index("CREATE TABLE user_consents ("))
        self.assertIn("NEVER run on Staging", ddl)

    def test_rejects_fk_to_unknown_table(self):
        bad = TEXT.replace("FK → users.user_id (CASCADE) | 1:1", "FK → userz.user_id (CASCADE) | 1:1")
        self.assertTrue(any("unknown table userz" in e for e in errors_for(bad)))

    def test_rejects_set_null_on_not_null_column(self):
        bad = TEXT.replace(
            "| actor_user_id | uuid | Y | | FK → users.user_id (SET NULL)",
            "| actor_user_id | uuid | N | | FK → users.user_id (SET NULL)",
        )
        self.assertTrue(any("SET NULL on NOT NULL" in e for e in errors_for(bad)))

    @unittest.skipIf(REQ_IDS is None, "docs/requirements (T04) not in tree")
    def test_rejects_unknown_requirement_id(self):
        bad = TEXT.replace("- 요구사항: FR-ACC-007", "- 요구사항: FR-ACC-999, FR-ACC-007", 1)
        self.assertTrue(any("unknown requirement" in e for e in errors_for(bad)))

    def test_rejects_catalog_cascade_into_personal_data(self):
        tables = cdd.parse(TEXT)
        user_skills = next(t for t in tables if t.name == "user_skills")
        col = next(c for c in user_skills.columns if c.name == "skill_id")
        col.fk = ("skills", "skill_id", "CASCADE")
        self.assertTrue(any("CASCADE from catalog skills" in e for e in cdd.validate(tables, REQ_IDS)))

    @unittest.skipIf(REQ_IDS is None, "docs/requirements (T04) not in tree")
    def test_rejects_missing_requirement_coverage(self):
        tables = cdd.parse(TEXT)
        for t in tables:
            t.features.discard("FR-AI-004")
        self.assertTrue(any("FR-AI-004" in e for e in cdd.validate(tables, REQ_IDS)))

if __name__ == "__main__":
    unittest.main()
