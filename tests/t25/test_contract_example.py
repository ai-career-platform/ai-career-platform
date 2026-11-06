"""Synthetic examples only: not a production schema or consent checker."""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path

FIXTURES = json.loads((Path(__file__).parent / 'fixtures.json').read_text(encoding='utf-8'))
SKILL_GAP = json.loads((Path(__file__).parent / 'skill_gap_example.json').read_text(encoding='utf-8'))
REQUIRED = ('entity_id', 'event_time', 'available_at', 'decision_time', 'source_id',
            'feature_version', 'dataset_version', 'split', 'usage_basis')


def validate_example(record):
    """Return stable error codes for the narrow proposed synthetic example."""
    errors = []
    for field in REQUIRED:
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append('missing:' + field)
    if errors:
        return errors
    if record['source_id'] != 'synthetic-fixture' or record['usage_basis'] != 'synthetic-only':
        errors.append('unapproved-example-source')
    if record['split'] not in ('train', 'validation', 'test'):
        errors.append('invalid-split')
    try:
        times = [datetime.fromisoformat(record[k].replace('Z', '+00:00'))
                 for k in ('event_time', 'available_at', 'decision_time')]
        if any(t.utcoffset() is None for t in times):
            raise ValueError('timezone required')
        if not times[0] <= times[1] <= times[2]:
            errors.append('time-order')
    except (ValueError, TypeError, OverflowError):
        errors.append('invalid-time')
    return errors


def validate_example_dataset(records):
    """Example isolation rule only: a synthetic entity must not cross splits."""
    errors = []
    splits_by_entity = {}
    for index, record in enumerate(records):
        row_errors = validate_example(record)
        errors.extend(f'row:{index}:{error}' for error in row_errors)
        if row_errors:
            continue
        entity = record['entity_id']
        previous = splits_by_entity.setdefault(entity, record['split'])
        if previous != record['split']:
            errors.append(f'cross-split-entity:{entity}')
    return errors


def select_available_example(records, decision_time):
    """Select the latest usable synthetic observation; reject ambiguous ties.

    This deliberately does not handle production data, permissions, or persistence.
    """
    cutoff = datetime.fromisoformat(decision_time.replace('Z', '+00:00'))
    if cutoff.utcoffset() is None:
        raise ValueError('timezone required')
    eligible = []
    identity = None
    for record in records:
        candidate = copy.deepcopy(record)
        candidate['decision_time'] = decision_time
        errors = validate_example(candidate)
        if not any(error.startswith('missing:') for error in errors):
            key = (candidate['entity_id'], candidate['feature_version'], candidate['dataset_version'], candidate['split'])
            if identity is None:
                identity = key
            elif identity != key:
                raise ValueError('mixed observation groups')
        if errors == ['time-order']:
            event = datetime.fromisoformat(candidate['event_time'].replace('Z', '+00:00'))
            available = datetime.fromisoformat(candidate['available_at'].replace('Z', '+00:00'))
            if event <= available and available > cutoff:
                continue
        if errors:
            raise ValueError(','.join(errors))
        eligible.append(candidate)
    if not eligible:
        return None
    latest = max(datetime.fromisoformat(r['available_at'].replace('Z', '+00:00')) for r in eligible)
    winners = [r for r in eligible if datetime.fromisoformat(r['available_at'].replace('Z', '+00:00')) == latest]
    if len(winners) != 1:
        raise ValueError('ambiguous latest observation')
    return winners[0]


class ContractExampleTests(unittest.TestCase):
    def test_skill_example_preserves_missing_self_assessment(self):
        # This checks the illustrative fixture, not an approved API/DB schema.
        self.assertEqual(SKILL_GAP['source_id'], 'synthetic-fixture')
        self.assertEqual(SKILL_GAP['observation_kind'], 'self_reported')
        self.assertTrue(1 <= SKILL_GAP['required_level'] <= 5)
        self.assertIsNone(SKILL_GAP['observed_level'])

    def test_valid_example_and_repeatability(self):
        self.assertEqual(validate_example(FIXTURES['valid']), [])
        self.assertEqual(validate_example(FIXTURES['valid']), validate_example(copy.deepcopy(FIXTURES['valid'])))

    def test_future_data_is_rejected(self):
        self.assertIn('time-order', validate_example(FIXTURES['future_available']))

    def test_missing_source_and_timezone_are_rejected(self):
        data = copy.deepcopy(FIXTURES['valid'])
        data['source_id'] = ''
        self.assertIn('missing:source_id', validate_example(data))
        data = copy.deepcopy(FIXTURES['valid'])
        data['available_at'] = '2026-01-02T00:00:00'
        self.assertIn('invalid-time', validate_example(data))

    def test_source_and_split_are_limited_to_example(self):
        data = copy.deepcopy(FIXTURES['valid'])
        data.update(source_id='unknown', split='production')
        self.assertEqual(validate_example(data), ['unapproved-example-source', 'invalid-split'])

    def test_same_synthetic_entity_cannot_cross_splits(self):
        training = copy.deepcopy(FIXTURES['valid'])
        evaluation = copy.deepcopy(training)
        evaluation['split'] = 'test'
        self.assertIn('cross-split-entity:synthetic-user-001',
                      validate_example_dataset([training, evaluation]))

    def test_different_entities_can_be_in_different_splits(self):
        training = copy.deepcopy(FIXTURES['valid'])
        evaluation = copy.deepcopy(training)
        evaluation.update(entity_id='synthetic-user-002', split='test')
        self.assertEqual(validate_example_dataset([training, evaluation]), [])

    def test_invalid_rows_do_not_create_false_split_comparisons(self):
        invalid = copy.deepcopy(FIXTURES['valid'])
        invalid.update(source_id='', split='test')
        self.assertEqual(validate_example_dataset([FIXTURES['valid'], invalid]),
                         ['row:1:missing:source_id'])

    def test_point_in_time_ignores_late_data_and_is_order_independent(self):
        early = copy.deepcopy(FIXTURES['valid'])
        late = copy.deepcopy(early)
        late['available_at'] = '2026-01-04T00:00:00Z'
        cutoff = '2026-01-03T00:00:00Z'
        self.assertEqual(select_available_example([late, early], cutoff), early)
        self.assertEqual(select_available_example([early, late], cutoff), early)
        self.assertIsNone(select_available_example([late], cutoff))

    def test_point_in_time_rejects_ambiguous_and_invalid_inputs(self):
        valid = copy.deepcopy(FIXTURES['valid'])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            select_available_example([valid, copy.deepcopy(valid)], valid['decision_time'])
        invalid = copy.deepcopy(valid)
        invalid['source_id'] = 'unapproved'
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            select_available_example([invalid], valid['decision_time'])

    def test_point_in_time_rejects_mixed_groups_even_when_late(self):
        valid = copy.deepcopy(FIXTURES['valid'])
        late = copy.deepcopy(valid)
        late.update(entity_id='synthetic-user-002', available_at='2026-01-04T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'mixed observation groups'):
            select_available_example([valid, late], valid['decision_time'])


if __name__ == '__main__':
    unittest.main()
