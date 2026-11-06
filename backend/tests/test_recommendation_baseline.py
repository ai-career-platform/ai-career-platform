from datetime import date, datetime
import pytest
from app.services.recommendation_baseline import Posting, recommend

TODAY = date(2026, 11, 6)


def p(id, skills=('python', 'sql'), expiry=TODAY, status='published'):
    return Posting(id, skills, 'synthetic-source', expiry, status)


def test_golden_ranking_and_explanations():
    result = recommend(['python'], [p('b'), p('a', ('python',)), p('c', ('sql',))], as_of=TODAY)
    assert [(x.posting_id, x.score) for x in result.items] == [('a', 100), ('b', 50), ('c', 0)]
    assert result.items[1].matched_skills == ('python',)
    assert result.items[1].missing_skills == ('sql',)
    assert '확률이 아닙니다' in result.limitation


def test_ties_filter_expired_closed_excluded_and_empty_requirements():
    result = recommend(['python'], [p('b'), p('a'), p('old', expiry=date(2026, 11, 5)),
                                  p('closed', status='closed'), p('hide'), p('none', ())],
                       as_of=TODAY, excluded_ids=['hide'])
    assert [x.posting_id for x in result.items] == ['a', 'b']


def test_hash_is_reproducible_across_input_order():
    one = recommend(['sql', 'python'], [p('b'), p('a')], as_of=TODAY)
    two = recommend(['python', 'sql'], [p('a'), p('b')], as_of=TODAY)
    assert one == two
    assert one.input_hash != recommend(['python'], [p('a'), p('b')], as_of=TODAY).input_hash


def test_reject_duplicates_bad_input_and_no_skills():
    for values, postings in [([], [p('a')]), (['python', 'python'], [p('a')]),
                             (['python'], [p('a'), p('a')]), (['python'], [p('a', ('x', 'x'))])]:
        with pytest.raises(ValueError):
            recommend(values, postings, as_of=TODAY)
    with pytest.raises(ValueError):
        recommend(['python'], [p('a')], as_of=datetime(2026, 11, 6))
