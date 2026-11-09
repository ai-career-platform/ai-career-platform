"""T45 opt-in PostgreSQL E2E. Destroys career schema ONLY in disposable T15_TEST_DATABASE_URL.

Never point T15_TEST_DATABASE_URL to Staging. Reuses the isolated T05 fixture.
"""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.repositories.recommendation_runs import runs, items, model_versions
from tests.conftest import bearer
from tests.test_auth_postgres import engine, pg_client, pytestmark, signup_body  # noqa: F401

API = "/api/v1"


def test_recommendation_run_postgres_store_read_owner_and_expiry(pg_client, engine):
    first = pg_client.post(API + "/auth/signup", json=signup_body("t45-user-one@example.com"))
    second = pg_client.post(API + "/auth/signup", json=signup_body("t45-user-two@example.com"))
    assert first.status_code == 201 and second.status_code == 201
    user = bearer(first.json()["access_token"])
    other = bearer(second.json()["access_token"])
    now = datetime.now(UTC)
    live, expired = uuid4(), uuid4()

    with Session(engine) as db, db.begin():
        skill_id = db.scalar(text("SELECT skill_id FROM career.skills WHERE code = 'PYTHON'"))
        company_id = db.scalar(text("SELECT company_id FROM career.companies LIMIT 1"))
        source_id = db.scalar(text("SELECT source_id FROM career.data_sources WHERE code='synthetic_seed'"))
        role_id = db.scalar(text("SELECT job_role_id FROM career.job_roles WHERE code='BACKEND_ENGINEER'"))
        assert all((skill_id, company_id, source_id, role_id))
        for posting_id, expiry in ((live, None), (expired, now - timedelta(hours=1))):
            db.execute(text("""INSERT INTO career.job_postings
                (job_posting_id, company_id, source_id, job_role_id, title, status, published_at, expires_at)
                VALUES (:id, :company, :source, :role, :title, 'published', :published, :expiry)"""),
                {"id": posting_id, "company": company_id, "source": source_id, "role": role_id,
                 "title": f"합성 검증 공고 {posting_id}", "published": now - timedelta(days=2), "expiry": expiry})
            db.execute(text("""INSERT INTO career.job_posting_skills
                (job_posting_id, skill_id, is_required, required_level)
                VALUES (:id, :skill, true, 3)"""), {"id": posting_id, "skill": skill_id})

    update = pg_client.put(API + "/me/skills", headers=user,
        json={"items": [{"skill_id": str(skill_id), "proficiency": 3}]})
    assert update.status_code == 200, update.text
    assert pg_client.get(API + "/recommendation-runs/latest", headers=user).status_code == 404
    generated = pg_client.post(API + "/recommendation-runs", headers=user, json={"limit": 50})
    assert generated.status_code == 201, generated.text
    body = generated.json()
    run_id = body["recommendation_run_id"]
    run_uuid = UUID(run_id)
    ids = {v["job_posting"]["job_posting_id"] for v in body["items"]}
    assert str(live) in ids and str(expired) not in ids
    assert body["status"] == "completed"
    assert body["model_version"]["kind"] == "rule"
    assert generated.headers["location"] == API + "/recommendation-runs/" + run_id
    assert pg_client.get(API + "/recommendation-runs/latest", headers=user).json() == body
    assert pg_client.get(API + "/recommendation-runs/" + run_id, headers=user).json() == body
    assert pg_client.get(API + "/recommendation-runs/" + run_id, headers=other).status_code == 404
    assert pg_client.get(API + "/recommendation-runs/latest", headers=other).status_code == 404
    assert pg_client.post(API + "/recommendation-runs", json={"limit": 20}).status_code == 401
    with Session(engine) as db:
        assert db.scalar(select(runs.c.recommendation_run_id).where(
            runs.c.recommendation_run_id == run_uuid)) is not None
        assert db.scalar(select(model_versions.c.model_code).where(
            model_versions.c.version == "skill-overlap-draft-v2")) == "skill_overlap_baseline"
        assert db.execute(select(items.c.rank).where(items.c.recommendation_run_id == run_uuid)).all()


def test_recommendation_run_postgres_feedback_latest_wins_and_get_is_read_only(pg_client, engine):
    signup = pg_client.post(API + "/auth/signup", json=signup_body("t45-feedback@example.com"))
    assert signup.status_code == 201
    user = bearer(signup.json()["access_token"])
    user_id = UUID(pg_client.get(API + "/me", headers=user).json()["user_id"])
    now = datetime.now(UTC)
    hidden, cleared = uuid4(), uuid4()

    with Session(engine) as db, db.begin():
        skill_id = db.scalar(text("SELECT skill_id FROM career.skills WHERE code = 'PYTHON'"))
        company_id = db.scalar(text("SELECT company_id FROM career.companies LIMIT 1"))
        source_id = db.scalar(text("SELECT source_id FROM career.data_sources WHERE code='synthetic_seed'"))
        for posting_id in (hidden, cleared):
            db.execute(text("""INSERT INTO career.job_postings
                (job_posting_id, company_id, source_id, title, status, published_at, expires_at)
                VALUES (:id, :company, :source, :title, 'published', :published, NULL)"""),
                {"id": posting_id, "company": company_id, "source": source_id,
                 "title": f"합성 피드백 공고 {posting_id}", "published": now - timedelta(days=1)})
            db.execute(text("""INSERT INTO career.job_posting_skills
                (job_posting_id, skill_id, is_required, required_level)
                VALUES (:id, :skill, true, 3)"""), {"id": posting_id, "skill": skill_id})
        # Latest feedback wins: hidden stays not_interested, cleared is re-included.
        for posting_id, action, age in ((hidden, "not_interested", 2), (cleared, "not_interested", 2),
                                        (cleared, "cleared", 1)):
            db.execute(text("""INSERT INTO career.recommendation_feedback
                (user_id, job_posting_id, feedback, created_at) VALUES (:u, :p, :f, :t)"""),
                {"u": user_id, "p": posting_id, "f": action, "t": now - timedelta(minutes=age)})

    assert pg_client.put(API + "/me/skills", headers=user,
        json={"items": [{"skill_id": str(skill_id), "proficiency": 3}]}).status_code == 200
    created = pg_client.post(API + "/recommendation-runs", headers=user)
    assert created.status_code == 201, created.text
    body = created.json()
    ids = {v["job_posting"]["job_posting_id"] for v in body["items"]}
    assert str(cleared) in ids and str(hidden) not in ids
    assert all(v["feedback"] is None for v in body["items"] if v["job_posting"]["job_posting_id"] == str(cleared))

    def counts():
        with Session(engine) as db:
            return (db.scalar(text("SELECT count(*) FROM career.recommendation_runs")),
                    db.scalar(text("SELECT count(*) FROM career.recommendation_items")))
    before = counts()
    for _ in range(2):
        assert pg_client.get(API + "/recommendation-runs/latest", headers=user).json() == body
        assert pg_client.get(created.headers["location"], headers=user).json() == body
    assert counts() == before == (1, len(body["items"]))
