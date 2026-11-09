"""T25 synthetic-only leakage checks; not a production privacy or ML proof."""
from datetime import datetime
import re
import unittest


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone aware")
    return parsed


def audit_synthetic_leakage(records):
    """Review-only checks for synthetic snapshots; never a production leakage guarantee."""
    if not isinstance(records, list):
        return ["invalid-dataset"]
    errors = []
    seen = {"entity_id": {}, "group_id": {}, "content_fingerprint": {}}
    timeline = {}
    for i, record in enumerate(records):
        prefix = f"row:{i}:"
        if not isinstance(record, dict):
            errors.append(prefix + "invalid-record")
            continue
        split = record.get("split")
        if split not in ("train", "validation", "test"):
            errors.append(prefix + "invalid-split")
            continue
        try:
            event = _timestamp(record.get("event_time"))
            available = _timestamp(record.get("available_at"))
            decision = _timestamp(record.get("decision_time"))
        except (ValueError, TypeError, OverflowError):
            errors.append(prefix + "invalid-time")
            continue
        if event > available:
            errors.append(prefix + "event-after-availability")
        if available > decision:
            errors.append(prefix + "future-feature")
        label = record.get("label_available_at")
        if label is not None:
            try:
                label_time = _timestamp(label)
            except (ValueError, TypeError, OverflowError):
                errors.append(prefix + "invalid-label-time")
                continue
        else:
            label_time = None
        flag = record.get("label_used_as_feature", False)
        if not isinstance(flag, bool):
            errors.append(prefix + "invalid-label-flag")
        elif flag and (label_time is None or label_time > decision):
            errors.append(prefix + "future-label-feature")
        for field in seen:
            value = record.get(field)
            if value is None and field != "entity_id":
                continue
            if not isinstance(value, str) or not value.strip():
                errors.append(prefix + "invalid-" + field.replace("_", "-"))
                continue
            key = re.sub(r"\s+", " ", value.strip()).casefold()
            other = seen[field].setdefault(key, split)
            if other != split:
                errors.append(prefix + "cross-split-" + field.replace("_", "-"))
        timeline.setdefault(split, []).append(decision)
    for older, newer in (("train", "validation"), ("validation", "test"), ("train", "test")):
        if older in timeline and newer in timeline and max(timeline[older]) >= min(timeline[newer]):
            errors.append(f"time-split-overlap:{older}-{newer}")
    return errors


def sample(split="train", day=3, **overrides):
    """Every identifier and timestamp in these tests is synthetic."""
    record = {
        "entity_id": f"synthetic-{split}",
        "group_id": f"group-{split}",
        "content_fingerprint": f"example-{split}",
        "split": split,
        "event_time": f"2026-01-{day-2:02d}T00:00:00Z",
        "available_at": f"2026-01-{day-1:02d}T00:00:00Z",
        "decision_time": f"2026-01-{day:02d}T00:00:00Z",
        "label_available_at": f"2026-01-{day+1:02d}T00:00:00Z",
        "label_used_as_feature": False,
    }
    record.update(overrides)
    return record


class LeakageGuardTests(unittest.TestCase):
    def test_clean_time_ordered_split(self):
        self.assertEqual(audit_synthetic_leakage(
            [sample("train", 3), sample("validation", 7), sample("test", 11)]), [])

    def test_future_data(self):
        self.assertIn("row:0:future-feature", audit_synthetic_leakage([
            sample(available_at="2026-01-09T00:00:00Z")]))

    def test_future_label_cannot_be_feature(self):
        self.assertIn("row:0:future-label-feature", audit_synthetic_leakage([
            sample(label_used_as_feature=True)]))

    def test_future_label_allowed_as_training_target(self):
        # Labels after decision time are acceptable as *targets*, not as input features.
        self.assertEqual(audit_synthetic_leakage([sample()]), [])

    def test_label_available_before_decision(self):
        self.assertEqual(audit_synthetic_leakage([sample(
            label_used_as_feature=True,
            label_available_at="2026-01-02T00:00:00Z")]), [])

    def test_group_leakage(self):
        a, b = sample("train", 3), sample("test", 11, group_id="  GROUP-TRAIN ")
        self.assertIn("row:1:cross-split-group-id", audit_synthetic_leakage([a, b]))

    def test_content_fingerprint_leakage(self):
        a, b = sample("train", 3), sample("test", 11,
                      content_fingerprint=" EXAMPLE-TRAIN ")
        self.assertIn("row:1:cross-split-content-fingerprint",
                      audit_synthetic_leakage([a, b]))

    def test_entity_leakage(self):
        a, b = sample("train", 3), sample("test", 11, entity_id="synthetic-train")
        self.assertIn("row:1:cross-split-entity-id", audit_synthetic_leakage([a, b]))

    def test_overlap(self):
        self.assertIn("time-split-overlap:train-test",
                      audit_synthetic_leakage([sample("train", 9), sample("test", 7)]))

    def test_malformed(self):
        self.assertEqual(audit_synthetic_leakage("bad"), ["invalid-dataset"])
        self.assertIn("row:0:invalid-record", audit_synthetic_leakage([None]))
        self.assertIn("row:0:invalid-time", audit_synthetic_leakage([
            sample(decision_time="2026-01-03T00:00:00")]))
        self.assertIn("row:0:invalid-label-time", audit_synthetic_leakage([
            sample(label_available_at="bad")]))

    def test_invalid_values(self):
        self.assertIn("row:0:invalid-split",
                      audit_synthetic_leakage([sample(split="production")]))
        self.assertIn("row:0:invalid-label-flag",
                      audit_synthetic_leakage([sample(label_used_as_feature="yes")]))
        self.assertIn("row:0:invalid-entity-id",
                      audit_synthetic_leakage([sample(entity_id="")]))

    def test_event_after_availability(self):
        self.assertIn("row:0:event-after-availability",
                      audit_synthetic_leakage([
                          sample(event_time="2026-01-03T00:00:00Z")]))


if __name__ == "__main__":
    unittest.main()
