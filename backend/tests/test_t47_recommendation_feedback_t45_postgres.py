"""T47 × T45 PostgreSQL E2E (선택 실행). 실제 T45 `POST /recommendation-runs`가 만든 실행·항목으로 T47 피드백을 검증한다.

T45 E2E와 같은 일회용 DB 픽스처(`T15_TEST_DATABASE_URL`, `career` 스키마를 지우고 T05 DDL·T10 Seed로 다시 만듦)를 쓴다.
**일회용 로컬/CI DB에서만** 실행한다. Staging DB 주소를 넣지 말 것. 합성 사용자·공고만 쓴다.

확인하는 것
- 소유권: T45가 기록한 내 실행에 있던 공고만 201. 다른 사용자의 실행 ID·추천되지 않은 공고는 404, 행 없음.
- T45 `GET /recommendation-runs/*`의 `items[].feedback`이 T47 최신 피드백(liked / not_interested / cleared→null)을 보여 준다.
- 다음 `POST /recommendation-runs`에서 최신 값이 `not_interested`인 공고만 빠지고, `cleared`로 정정하면 다시 들어온다.
- 중복(같은 값 재전송)은 새 이력·감사 행을 만들지 않는다.
"""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.recommendation_feedback import AUDIT_ACTION
from tests.conftest import bearer
from tests.test_auth_postgres import engine, pg_client, pytestmark, signup_body  # noqa: F401

API = "/api/v1"


def _seed_postings(db_engine, count: int) -> tuple[UUID, list[UUID]]:
    now = datetime.now(UTC)
    ids = [uuid4() for _ in range(count)]
    with Session(db_engine) as db, db.begin():
        skill_id = db.scalar(text("SELECT skill_id FROM career.skills WHERE code = 'PYTHON'"))
        company_id = db.scalar(text("SELECT company_id FROM career.companies LIMIT 1"))
        source_id = db.scalar(text("SELECT source_id FROM career.data_sources WHERE code='synthetic_seed'"))
        assert all((skill_id, company_id, source_id))
        for n, posting_id in enumerate(ids):
            db.execute(text("""INSERT INTO career.job_postings
                (job_posting_id, company_id, source_id, title, status, published_at, expires_at)
                VALUES (:id, :company, :source, :title, 'published', :published, NULL)"""),
                {"id": posting_id, "company": company_id, "source": source_id,
                 "title": f"T47 합성 피드백 공고 {n}", "published": now - timedelta(days=1, minutes=n)})
            db.execute(text("""INSERT INTO career.job_posting_skills
                (job_posting_id, skill_id, is_required, required_level)
                VALUES (:id, :skill, true, 3)"""), {"id": posting_id, "skill": skill_id})
    return skill_id, ids


def _user(client, email, skill_id):
    signup = client.post(API + "/auth/signup", json=signup_body(email))
    assert signup.status_code == 201, signup.text
    headers = bearer(signup.json()["access_token"])
    put = client.put(API + "/me/skills", headers=headers,
                        json={"items": [{"skill_id": str(skill_id), "proficiency": 3}]})
    assert put.status_code == 200, put.text
    return headers


def _feedback_map(run_body) -> dict[str, str | None]:
    return {v["job_posting"]["job_posting_id"]: v["feedback"] for v in run_body["items"]}


def _count(db_engine, sql, **params) -> int:
    with Session(db_engine) as db:
        return db.scalar(text(sql), params)


def test_feedback_on_real_t45_runs_drives_item_feedback_and_next_run(pg_client, engine):  # noqa: F811
    skill_id, (liked, hidden, untouched) = _seed_postings(engine, 3)
    alice = _user(pg_client, "t47-t45-alice@example.com", skill_id)
    bob = _user(pg_client, "t47-t45-bob@example.com", skill_id)
    alice_id = UUID(pg_client.get(API + "/me", headers=alice).json()["user_id"])

    created = pg_client.post(API + "/recommendation-runs", headers=alice, json={"limit": 50})
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["recommendation_run_id"]
    assert {str(liked), str(hidden), str(untouched)} <= set(_feedback_map(run))
    assert all(value is None for value in _feedback_map(run).values())

    def post(headers, posting, value, run_ref=run_id):
        body = {"job_posting_id": str(posting), "feedback": value}
        if run_ref is not None:
            body["recommendation_run_id"] = run_ref
        return pg_client.post(API + "/recommendation-feedback", headers=headers, json=body)

    first = post(alice, liked, "liked")
    assert first.status_code == 201, first.text
    assert post(alice, liked, "liked").json()["feedback_id"] == first.json()["feedback_id"]  # 멱등
    assert post(alice, hidden, "not_interested", run_ref=None).status_code == 201  # run_id 생략: 내 실행 아무거나

    # 소유권: 다른 사용자는 Alice의 실행 ID로도, 추천받지 않은 공고로도 피드백할 수 없다 (404, 행 없음).
    assert post(bob, liked, "liked").status_code == 404
    assert post(bob, liked, "liked", run_ref=None).status_code == 404
    assert post(alice, liked, "liked", run_ref=str(uuid4())).status_code == 404
    bob_id = UUID(pg_client.get(API + "/me", headers=bob).json()["user_id"])
    assert _count(engine, "SELECT count(*) FROM career.recommendation_feedback WHERE user_id = :u", u=bob_id) == 0

    # T45 GET은 T47 최신 피드백을 보여 주고, 읽기 전용이다.
    shown = _feedback_map(pg_client.get(API + "/recommendation-runs/" + run_id, headers=alice).json())
    assert shown[str(liked)] == "liked" and shown[str(hidden)] == "not_interested" and shown[str(untouched)] is None
    assert _feedback_map(pg_client.get(API + "/recommendation-runs/latest", headers=alice).json()) == shown

    # 다음 실행: not_interested 공고만 빠지고, liked 공고는 남아 피드백이 붙는다.
    second = pg_client.post(API + "/recommendation-runs", headers=alice, json={"limit": 50}).json()
    second_map = _feedback_map(second)
    assert str(hidden) not in second_map
    assert second_map[str(liked)] == "liked" and second_map[str(untouched)] is None

    # 정정: 첫 실행 기준으로 cleared를 보내면 다음 실행에 다시 들어오고 feedback은 null.
    assert post(alice, hidden, "cleared").status_code == 201
    third = _feedback_map(pg_client.post(API + "/recommendation-runs", headers=alice, json={"limit": 50}).json())
    assert str(hidden) in third and third[str(hidden)] is None

    rows = _count(engine, "SELECT count(*) FROM career.recommendation_feedback WHERE user_id = :u", u=alice_id)
    audits = _count(engine, "SELECT count(*) FROM career.audit_events WHERE actor_user_id = :u AND action_code = :a",
                    u=alice_id, a=AUDIT_ACTION)
    assert rows == audits == 3  # liked, not_interested, cleared (중복 1건은 행·감사 없음)
    run_ref = _count(engine, """SELECT count(*) FROM career.recommendation_feedback
        WHERE user_id = :u AND recommendation_run_id = :r""", u=alice_id, r=UUID(run_id))
    assert run_ref == 2  # run_id를 보낸 두 건만 실행을 가리킨다


def test_concurrent_same_feedback_on_real_t45_run_creates_one_row(pg_client, engine):  # noqa: F811
    """advisory lock: 같은 사용자·공고에 동시에 같은 값을 보내도 이력·감사 행은 1건 (나머지는 멱등 응답).

    경쟁을 실제로 만들기 위해 스레드 수만큼 연결을 가진 별도 엔진을 쓰고, 최신 값 조회 직후 잠깐 멈춘다.
    (잠금이 없으면 여러 요청이 "기록 없음"을 보고 각각 INSERT 하게 되어 이 테스트가 실패한다.)
    """
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.core.config import DatabaseSettings
    from app.db import create_db_engine
    from app.repositories.recommendation_feedback import SqlRecommendationFeedbackRepository
    from app.schemas.recommendation_feedback import RecommendationFeedbackInput
    from app.services.recommendation_feedback import RecommendationFeedbackService
    from tests.test_auth_postgres import DB_URL

    class SlowReadRepository(SqlRecommendationFeedbackRepository):
        def latest_feedback(self, user_id, job_posting_ids):
            result = super().latest_feedback(user_id, job_posting_ids)
            time.sleep(0.2)  # widen the read-then-insert window
            return result

    skill_id, (posting,) = _seed_postings(engine, 1)
    alice = _user(pg_client, "t47-t45-race@example.com", skill_id)
    alice_id = UUID(pg_client.get(API + "/me", headers=alice).json()["user_id"])
    run_id = UUID(pg_client.post(API + "/recommendation-runs", headers=alice, json={"limit": 50})
                  .json()["recommendation_run_id"])
    workers = 6
    race_engine = create_db_engine(DatabaseSettings(url=DB_URL, pool_size=workers, timeout=10))
    gate = Barrier(workers)

    def submit(_):
        with Session(race_engine) as db:
            db.execute(text("SELECT 1"))  # hold a connection before the barrier
            service = RecommendationFeedbackService(SlowReadRepository(db))
            gate.wait()
            return service.create(alice_id, RecommendationFeedbackInput(
                recommendation_run_id=run_id, job_posting_id=posting, feedback="not_interested"), None).feedback_id

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            ids = set(pool.map(submit, range(workers)))
    finally:
        race_engine.dispose()
    assert len(ids) == 1
    assert _count(engine, "SELECT count(*) FROM career.recommendation_feedback WHERE user_id = :u", u=alice_id) == 1
    assert _count(engine, "SELECT count(*) FROM career.audit_events WHERE actor_user_id = :u AND action_code = :a",
                  u=alice_id, a=AUDIT_ACTION) == 1
    nxt = _feedback_map(pg_client.post(API + "/recommendation-runs", headers=alice, json={"limit": 50}).json())
    assert str(posting) not in nxt
