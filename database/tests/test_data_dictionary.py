"""T05: unit tests for database/model/check_data_dictionary.py (no database needed).

Run: python3 -B -m unittest discover -s database/tests -p "test_data_dictionary.py" -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "database" / "model"))
import check_data_dictionary as cdd  # noqa: E402

TEXT = cdd.DICTIONARY.read_text(encoding="utf-8")


def errors_for(text):
    return cdd.validate(cdd.parse(text))


class DataDictionaryTest(unittest.TestCase):
    def test_current_dictionary_is_valid(self):
        self.assertEqual(errors_for(TEXT), [])

    def test_every_kept_feature_maps_to_a_table(self):
        mapped = set().union(*(t.features for t in cdd.parse(TEXT)))
        self.assertEqual(cdd.ALL_FEATURES - mapped, cdd.DROPPED_FEATURES | cdd.NO_DATA_FEATURES)

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

    def test_rejects_mapping_to_dropped_feature(self):
        bad = TEXT.replace("- 기능: F-004, F-005, F-028 (", "- 기능: F-004, F-005, F-027, F-028 (")
        self.assertTrue(any("dropped feature" in e for e in errors_for(bad)))

    def test_rejects_catalog_cascade_into_personal_data(self):
        tables = cdd.parse(TEXT)
        user_skills = next(t for t in tables if t.name == "user_skills")
        col = next(c for c in user_skills.columns if c.name == "skill_id")
        col.fk = ("skills", "skill_id", "CASCADE")
        self.assertTrue(any("CASCADE from catalog skills" in e for e in cdd.validate(tables)))

    def test_rejects_missing_feature_coverage(self):
        tables = cdd.parse(TEXT)
        for t in tables:
            t.features.discard("F-023")
        self.assertTrue(any("F-023" in e for e in cdd.validate(tables)))

if __name__ == "__main__":
    unittest.main()
