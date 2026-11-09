"""T47 PostgreSQL 저장소 테스트 (선택 실행, **HOLD**) — T08 Migration + T10 Seed가 적용된 **로컬 일회용 DB** 기준.

`T47_TEST_DATABASE_URL`을 지정했을 때만 실행한다. 호스트가 localhost/127.0.0.1이 아니면 실행을 거부한다.
테스트마다 바깥 트랜잭션을 열고 저장소의 commit은 SAVEPOINT로만 처리한 뒤, 끝나면 전부 롤백한다
(Seed·다른 데이터는 바뀌지 않는다). 추천 실행·항목은 T45가 머지되기 전이라 테스트가 직접 넣는다.

    # 준비: tests/test_t18_job_postings_postgres.py 머리말과 같은 절차 (database/migrations/README.md)
    export T47_TEST_DATABASE_URL=postgresql://USER@127.0.0.1:5432/career_dev
    python -m pytest tests/test_t47_recommendation_feedback_postgres.py -v

작성 시점(T47)에는 로컬 PostgreSQL을 띄울 수 없어 **미실행**이다. 실제 DB 검증은 T45 머지 후 이 파일로 한다.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings
from app.db import create_db_engine
from app.repositories.recommendation_feedback import SqlRecommendationFeedbackRepository
from app.schemas.recommendation_feedback import RecommendationFeedbackInput
from app.services.recommendation_feedback import AUDIT_ACTION, RecommendationFeedbackService

DB_URL = os.environ.get("T47_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="T47_TEST_DATABASE_URL not set")
RUN = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def engine():
    if make_url(DB_URL).host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("T47 Postgres tests run only against a local disposable DB")
    eng = create_db_engine(DatabaseSettings(url=DB_URL, pool_size=2, timeout=5))
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """(session, ids). 모든 변경은 테스트 끝에 롤백된다."""
    conn = engine.connect()
    outer = conn.begin()
    ids = {k: uuid.uuid4() for k in ["alice", "bob", "model", "company", "post_a", "post_b", "run_a", "run_b"]}
    q = lambda sql, **p: conn.execute(text(sql), p)
    for who in ("alice", "bob"):
        q("INSERT INTO career.users (user_id, email, email_canonical, display_name) VALUES (:id, :e, :e, :n)",
          id=ids[who], e=f"t47-{who}-{RUN}@example.invalid", n=f"T47 {who}")
    q("INSERT INTO career.model_versions (model_version_id, model_code, version, kind) VALUES (:id, :c, '1', 'rule')",
      id=ids["model"], c=f"t47_match_rule_{RUN}")
    q("""INSERT INTO career.companies (company_id, name, source_id)
         SELECT :id, :n, source_id FROM career.data_sources WHERE code = 'synthetic_seed'""",
      id=ids["company"], n=f"T47IT 합성기업 {RUN}")
    for key in ("post_a", "post_b"):
        q("""INSERT INTO career.job_postings (job_posting_id, company_id, source_id, title, status, published_at)
             SELECT :id, :c, source_id, :t, 'published', now() FROM career.data_sources WHERE code = 'synthetic_seed'""",
          id=ids[key], c=ids["company"], t=f"T47IT {RUN} {key}")
    for run, who, posts in (("run_a", "alice", ["post_a", "post_b"]), ("run_b", "bob", ["post_a"])):
        q("INSERT INTO career.recommendation_runs (recommendation_run_id, user_id, model_version_id) VALUES (:r, :u, :m)",
          r=ids[run], u=ids[who], m=ids["model"])
        for rank, post in enumerate(posts, start=1):
            q("""INSERT INTO career.recommendation_items (recommendation_run_id, job_posting_id, rank, score, reason)
                 VALUES (:r, :p, :k, 50, 'T47 합성 추천 이유')""", r=ids[run], p=ids[post], k=rank)
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session, ids
    finally:
        session.close()
        outer.rollback()
        conn.close()


def _create(service, user, post, value, run=None):
    return service.create(user, RecommendationFeedbackInput(recommendation_run_id=run, job_posting_id=post,
                                                            feedback=value), "req-t47-pg-00001")


def _rows(session, user, post):
    return session.execute(text("""
        SELECT feedback FROM career.recommendation_feedback WHERE user_id = :u AND job_posting_id = :p
        ORDER BY created_at, feedback_id"""), {"u": user, "p": post}).scalars().all()


def test_ownership_duplicate_correction_and_audit(db):
    session, ids = db
    service = RecommendationFeedbackService(SqlRecommendationFeedbackRepository(session))
    first = _create(service, ids["alice"], ids["post_a"], "liked", ids["run_a"])
    assert _create(service, ids["alice"], ids["post_a"], "liked").feedback_id == first.feedback_id
    _create(service, ids["alice"], ids["post_a"], "not_interested", ids["run_a"])
    _create(service, ids["alice"], ids["post_a"], "cleared")
    assert _rows(session, ids["alice"], ids["post_a"]) == ["liked", "not_interested", "cleared"]
    assert service.current_feedback(ids["alice"], [ids["post_a"], ids["post_b"]]) == {
        ids["post_a"]: None, ids["post_b"]: None}
    audits = session.execute(text("""SELECT count(*) FROM career.audit_events
        WHERE actor_user_id = :u AND action_code = :a AND request_id = 'req-t47-pg-00001'"""),
        {"u": ids["alice"], "a": AUDIT_ACTION}).scalar_one()
    assert audits == 3


def test_other_users_run_and_unrecommended_posting_are_not_found(db):
    from app.core.errors import AppError, ErrorCode

    session, ids = db
    service = RecommendationFeedbackService(SqlRecommendationFeedbackRepository(session))
    for user, post, run in ((ids["alice"], ids["post_a"], ids["run_b"]), (ids["bob"], ids["post_b"], None),
                            (ids["bob"], ids["post_b"], ids["run_a"])):
        with pytest.raises(AppError) as err:
            _create(service, user, post, "liked", run)
        assert err.value.code == ErrorCode.NOT_FOUND
    assert _rows(session, ids["bob"], ids["post_b"]) == []


def test_per_user_isolation_and_not_interested_exclusion(db):
    session, ids = db
    service = RecommendationFeedbackService(SqlRecommendationFeedbackRepository(session))
    _create(service, ids["alice"], ids["post_a"], "not_interested", ids["run_a"])
    _create(service, ids["bob"], ids["post_a"], "liked", ids["run_b"])
    assert service.not_interested_ids(ids["alice"], [ids["post_a"]]) == {ids["post_a"]}
    assert service.not_interested_ids(ids["bob"], [ids["post_a"]]) == set()
