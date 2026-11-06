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


if __name__ == '__main__':
    unittest.main()
