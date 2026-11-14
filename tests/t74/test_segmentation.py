"""T74 군집 baseline 테스트. 합성 데이터만 사용하며 DB·네트워크가 필요 없습니다.

    python -B -m unittest discover -s tests/t74 -v
"""
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ml.segmentation import baseline as seg  # noqa: E402

AS_OF = "2026-11-11T00:00:00+00:00"


def _factory():
    spec = importlib.util.spec_from_file_location("synth_factory", ROOT / "database" / "fixtures" / "synth_factory.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["synth_factory"] = module
    spec.loader.exec_module(module)
    return module


def t147_rows(seed=74, users=120):
    """T147 합성 공장이 만드는 AI 피처 행 (개인정보 없음)."""
    ds = _factory().generate(seed, users, 5, 10)
    return [dict(f) for f in ds.features]


def blob_rows(per_group=15, groups=3, seed=1):
    """서로 겹치지 않는 기술 묶음을 가진 명확한 합성 군집."""
    rng = random.Random(seed)
    rows = []
    for g in range(groups):
        for i in range(per_group):
            skills = {f"S{g}_{j}": rng.randint(3, 5) for j in range(4)}
            rows.append({"entity_id": f"u-{g}-{i}", "skills": skills, "dataset_version": "t74.test", "source": "synthetic_seed",
                         "block": f"B{g}"})
    return rows


class MetricTests(unittest.TestCase):
    def test_ari_ignores_label_names_and_detects_disagreement(self):
        self.assertEqual(seg.adjusted_rand_index([0, 0, 1, 1], ["x", "x", "y", "y"]), 1.0)
        self.assertLess(seg.adjusted_rand_index([0, 0, 1, 1], [0, 1, 0, 1]), 0.1)
        with self.assertRaises(seg.SegmentationError):
            seg.adjusted_rand_index([0, 1], [0])

    def test_silhouette_high_for_separated_clusters(self):
        X = [[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [5.0, 5.0], [5.1, 5.0], [5.0, 5.1]]
        self.assertGreater(seg.silhouette(X, [0, 0, 0, 1, 1, 1]), 0.9)
        self.assertLess(seg.silhouette(X, [0, 1, 0, 1, 0, 1]), 0.1)
        with self.assertRaises(seg.SegmentationError):
            seg.silhouette(X, [0] * 6)

    def test_kmeans_recovers_separated_groups_and_is_deterministic(self):
        rows = blob_rows()
        X, _ = seg.build_matrix(rows)
        labels, _ = seg.kmeans(X, 3, seed=7)
        self.assertEqual(seg.adjusted_rand_index(labels, [r["block"] for r in rows]), 1.0)
        self.assertEqual(seg.kmeans(X, 3, seed=7), (labels, seg.kmeans(X, 3, seed=7)[1]))
        with self.assertRaises(seg.SegmentationError):
            seg.kmeans(X, 1, seed=7)


class InputGuardTests(unittest.TestCase):
    def setUp(self):
        self.rows = blob_rows(per_group=6, groups=2)

    def test_forbidden_attribute_is_rejected(self):
        for key in ("gender", "age", "email"):
            rows = blob_rows(per_group=6, groups=2)
            rows[0][key] = "x"
            with self.assertRaisesRegex(seg.SegmentationError, "forbidden"):
                seg.prepare_rows(rows, AS_OF)
        rows = blob_rows(per_group=6, groups=2)
        rows[0]["skills"]["Age"] = 3  # 기술 키 안에 숨긴 경우도 거부
        with self.assertRaisesRegex(seg.SegmentationError, "forbidden"):
            seg.prepare_rows(rows, AS_OF)

    def test_unapproved_source_duplicates_and_bad_values_are_rejected(self):
        self.rows[0]["source"] = "scraped_real_users"
        with self.assertRaisesRegex(seg.SegmentationError, "source"):
            seg.prepare_rows(self.rows, AS_OF)
        rows = blob_rows(per_group=6, groups=2)
        rows[1]["entity_id"] = rows[0]["entity_id"]
        with self.assertRaisesRegex(seg.SegmentationError, "duplicate"):
            seg.prepare_rows(rows, AS_OF)
        for bad in (0, 6, True, 2.5, "3"):
            rows = blob_rows(per_group=6, groups=2)
            rows[0]["skills"]["S0_0"] = bad
            with self.assertRaisesRegex(seg.SegmentationError, "proficiency"):
                seg.prepare_rows(rows, AS_OF)
        rows = blob_rows(per_group=6, groups=2)
        rows[0]["dataset_version"] = "other"
        with self.assertRaisesRegex(seg.SegmentationError, "mixed"):
            seg.prepare_rows(rows, AS_OF)
        with self.assertRaisesRegex(seg.SegmentationError, "timezone"):
            seg.prepare_rows(blob_rows(per_group=6, groups=2), "2026-11-11T00:00:00")

    def test_no_consent_and_future_rows_are_excluded_and_counted(self):
        rows = blob_rows(per_group=8, groups=2)
        rows[0]["consent"] = False
        rows[1]["available_at"] = "2026-11-12T00:00:00+00:00"   # 기준 시각 이후 → 누수 방지
        rows[2]["available_at"] = "2026-11-10T00:00:00+00:00"   # 이전 → 사용
        kept, info = seg.prepare_rows(rows, AS_OF)
        self.assertEqual(info["excluded"], {"available_after_as_of": 1, "no_consent": 1})
        self.assertEqual(info["used_rows"], len(rows) - 2)
        self.assertNotIn(rows[0], kept)
        self.assertNotIn(rows[1], kept)

    def test_excluded_rows_do_not_influence_result(self):
        rows = blob_rows(per_group=8, groups=2)
        extra = {"entity_id": "late", "skills": {"S0_0": 5, "S1_0": 5}, "dataset_version": "t74.test",
                 "source": "synthetic_seed", "available_at": "2026-12-01T00:00:00+00:00"}
        a, _ = seg.run(rows, AS_OF, (2, 3))
        b, _ = seg.run(rows + [extra], AS_OF, (2, 3))
        a["data"].pop("input_rows"), b["data"].pop("input_rows")
        b["data"].pop("excluded")
        a["data"].pop("excluded")
        a.pop("report_fingerprint"), b.pop("report_fingerprint")
        self.assertEqual(a, b)

    def test_too_few_rows_fail(self):
        with self.assertRaisesRegex(seg.SegmentationError, "not enough"):
            seg.run(blob_rows(per_group=2, groups=2), AS_OF)


class ReportTests(unittest.TestCase):
    def test_report_has_versions_and_hides_identifiers_and_small_clusters(self):
        rows = blob_rows(per_group=12, groups=3)
        rows += [{"entity_id": f"odd-{i}", "skills": {"RARE": 5, "S0_0": 1}, "dataset_version": "t74.test",
                  "source": "synthetic_seed"} for i in range(3)]
        report, labels = seg.run(rows, AS_OF, (2, 7))
        text = json.dumps(report, ensure_ascii=False)
        self.assertEqual(report["model"]["segmentation_version"], seg.SEGMENTATION_VERSION)
        self.assertEqual(report["data"]["dataset_version"], "t74.test")
        for row in rows:
            self.assertNotIn(row["entity_id"], text)          # 개인 식별자 미포함
        self.assertEqual(len(labels), len(rows))
        for entry in report["cluster_sizes"]:
            self.assertTrue(isinstance(entry["size"], str) or entry["size"] >= seg.K_ANON_MIN)
        self.assertTrue(report["target_check"]["silhouette"])
        self.assertTrue(report["target_check"]["seed_stability"])

    def test_same_input_and_seed_reproduce_exact_report(self):
        rows = t147_rows()
        a, la = seg.run(rows, AS_OF, (2, 6), seed=74)
        b, lb = seg.run(list(rows), AS_OF, (2, 6), seed=74)
        self.assertEqual(a, b)
        self.assertEqual(la, lb)
        self.assertEqual(a["data"]["dataset_version"], "t147.2:seed74")

    def test_cli_reproduces_in_a_fresh_process(self):
        rows = t147_rows(users=80)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "f.jsonl"
            src.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
            outs = []
            for name in ("a.json", "b.json"):
                out = Path(tmp) / name
                proc = subprocess.run(
                    [sys.executable, "-B", "-m", "ml.segmentation.baseline", "--input", str(src), "--as-of", AS_OF,
                     "--k-max", "5", "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                outs.append(out.read_text(encoding="utf-8"))
            self.assertEqual(outs[0], outs[1])

    def test_cli_fails_cleanly_on_forbidden_input(self):
        rows = t147_rows(users=20)
        rows[0]["gender"] = "x"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "f.jsonl"
            src.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            proc = subprocess.run([sys.executable, "-B", "-m", "ml.segmentation.baseline", "--input", str(src),
                                   "--as-of", AS_OF], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("T74_SEGMENTATION=FAIL", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class FairnessTests(unittest.TestCase):
    def test_independent_groups_pass_and_skewed_groups_are_flagged(self):
        rows = blob_rows(per_group=30, groups=3)
        rng = random.Random(5)
        independent = {r["entity_id"]: rng.choice(["G1", "G2"]) for r in rows}
        skewed = {r["entity_id"]: ("G1" if r["block"] == "B0" else "G2") for r in rows}
        ok, _ = seg.run(rows, AS_OF, (3, 3), groups_by_entity=independent)
        bad, _ = seg.run(rows, AS_OF, (3, 3), groups_by_entity=skewed)
        self.assertTrue(ok["representation"]["within_range"], ok["representation"])
        self.assertFalse(bad["representation"]["within_range"])
        self.assertTrue(bad["representation"]["flagged"])

    def test_group_labels_never_change_the_clustering(self):
        rows = blob_rows(per_group=15, groups=3)
        groups = {r["entity_id"]: ("G1" if r["block"] == "B0" else "G2") for r in rows}
        _, with_groups = seg.run(rows, AS_OF, (3, 3), groups_by_entity=groups)
        _, without = seg.run(rows, AS_OF, (3, 3))
        self.assertEqual(with_groups, without)

    def test_external_agreement_is_reported_for_reference_labels(self):
        rows = blob_rows(per_group=15, groups=3)
        report, _ = seg.run(rows, AS_OF, (3, 3), reference_by_entity={r["entity_id"]: r["block"] for r in rows})
        self.assertEqual(report["external_agreement_ari"], 1.0)


if __name__ == "__main__":
    unittest.main()
