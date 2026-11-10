"""T41 PostgreSQL 통합 테스트 (선택 실행) — T05 검증용 DDL + T10 Seed 위에서 적합도 계산·저장·조회.

`T15_TEST_DATABASE_URL`을 지정했을 때만 실행한다(T15 통합 테스트와 같은 일회용 DB 사용).
지정한 DB의 `career` 스키마를 지우고 다시 만들므로 **일회용 로컬 DB에서만** 쓴다. 공유 Staging DB 주소 금지.

    $env:T15_TEST_DATABASE_URL = "postgresql://postgres:t15local@127.0.0.1:55432/postgres"
    .venv\\Scripts\\python.exe -m pytest tests/test_matches_postgres.py -v

T10 Seed에는 `model_versions`가 없으므로 테스트에서 승인된 `match_rule` v1을 넣는다
(운영 등록 SQL은 backend/docs/MATCH_RULE.md 참고).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import jwt
import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import API_V1_PREFIX
from app.repositories.job_postings import job_posting_skills, job_postings
from app.repositories.matching import match_evaluations
from app.repositories.my_skills import user_skills
from app.services import match_rule
from tests.conftest import bearer
from tests.test_auth_postgres import CONSENTS, engine, pg_client, pytestmark  # noqa: F401  (픽스처·skip 조건 재사용)

MATCHES = f"{API_V1_PREFIX}/matches"
jp, jps, me = job_postings.c, job_posting_skills.c, match_evaluations.c


@pytest.fixture
def rule_v1(engine):  # noqa: F811
    with Session(engine) as db, db.begin():
        return db.execute(text(
            "INSERT INTO career.model_versions (model_code, version, kind, description, approved_at)"
            " VALUES (:code, :version, :kind, 'T41 test', :approved_at) RETURNING model_version_id"
        ), {"code": match_rule.MODEL_CODE, "version": match_rule.VERSION, "kind": match_rule.KIND,
            "approved_at": datetime(2026, 11, 9, tzinfo=UTC)}).scalar_one()


def signup(client, email):
    r = client.post(f"{API_V1_PREFIX}/auth/signup", json={
        "email": email, "password": "correct-horse-battery-1", "display_name": "적합도", "consents": CONSENTS,
    })
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return bearer(token), uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"])


def seed_posting_with_skills(engine):
    """Seed의 게시 공고 하나와 그 요구 기술(필수 여부·수준)."""
    with Session(engine) as db:
        posting_id = db.scalar(
            select(jp.job_posting_id).where(jp.status == "published").order_by(jp.job_posting_id)
        )
        reqs = db.execute(
            select(jps.skill_id, jps.required_level, jps.is_required)
            .where(jps.job_posting_id == posting_id)
            .order_by(jps.skill_id)
        ).all()
    return posting_id, reqs


def test_match_flow_against_postgres(pg_client, engine, rule_v1):  # noqa: F811
    headers, user_id = signup(pg_client, "match@example.com")
    posting_id, reqs = seed_posting_with_skills(engine)
    assert reqs, "seed posting has no skills"

    # 보유 기술 없음 → 400, 저장 없음
    r = pg_client.post(MATCHES, json={"job_posting_id": str(posting_id)}, headers=headers)
    assert r.status_code == 400 and r.json()["code"] == "NO_USER_SKILLS"

    # 첫 요구 기술은 충족, 둘째는 요구보다 1 낮게 등록
    (s1, lvl1, _), (s2, lvl2, _) = reqs[0], reqs[1]
    with Session(engine) as db, db.begin():
        db.execute(insert(user_skills), [{"user_id": user_id, "skill_id": s1, "proficiency": lvl1},
                                         {"user_id": user_id, "skill_id": s2, "proficiency": max(lvl2 - 1, 1)}])

    r = pg_client.post(MATCHES, json={"job_posting_id": str(posting_id)}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    expected = match_rule.evaluate(
        [match_rule.Requirement(s, lvl, req) for s, lvl, req in reqs],
        {s1: lvl1, s2: max(lvl2 - 1, 1)}, set(),
    )
    assert body["score"] == float(expected.score)
    assert body["matched_skill_count"] == expected.matched_skill_count >= 1

    # 저장 내용: 계산 기준 ID, numeric(5,2) 점수, 한계 설명
    with Session(engine) as db:
        row = db.execute(
            select(me.user_id, me.job_posting_id, me.job_role_id, me.model_version_id, me.score, me.limitations)
            .where(me.match_id == uuid.UUID(body["match_id"]))
        ).one()
    assert (row.user_id, row.job_posting_id, row.job_role_id, row.model_version_id) == (user_id, posting_id, None, rule_v1)
    assert row.score == expected.score and isinstance(row.score, Decimal)
    assert row.limitations == match_rule.LIMIT_BASE

    # 조회: 본인 200, 다른 사람 404
    assert pg_client.get(f"{MATCHES}/{body['match_id']}", headers=headers).json() == body
    other, _ = signup(pg_client, "other-match@example.com")
    assert pg_client.get(f"{MATCHES}/{body['match_id']}", headers=other).status_code == 404


def test_draft_posting_is_404_and_role_match_works(pg_client, engine, rule_v1):  # noqa: F811
    headers, user_id = signup(pg_client, "role-match@example.com")
    with Session(engine) as db, db.begin():
        draft_id = db.scalar(select(jp.job_posting_id).where(jp.status == "draft"))
        role_id, skill_id, level = db.execute(text(
            "SELECT job_role_id, skill_id, required_level FROM career.job_role_skills ORDER BY job_role_id, skill_id LIMIT 1"
        )).one()
        db.execute(insert(user_skills).values(user_id=user_id, skill_id=skill_id, proficiency=level))

    assert pg_client.post(MATCHES, json={"job_posting_id": str(draft_id)}, headers=headers).status_code == 404
    r = pg_client.post(MATCHES, json={"job_role_id": str(role_id)}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["target"] == {"job_posting_id": None, "job_role_id": str(role_id)}
    assert r.json()["matched_skill_count"] >= 1


def test_failed_result_fits_db_checks_and_score_range_is_enforced(pg_client, engine, rule_v1):  # noqa: F811
    _, user_id = signup(pg_client, "check@example.com")
    with Session(engine) as db:
        posting_id = db.scalar(select(jp.job_posting_id).where(jp.status == "published"))
    with Session(engine) as db, db.begin():
        db.execute(insert(match_evaluations).values(user_id=user_id, job_posting_id=posting_id, model_version_id=rule_v1,
                                                    status="failed", limitations=match_rule.LIMIT_NO_REQUIREMENTS))
    with pytest.raises(IntegrityError), Session(engine) as db, db.begin():
        db.execute(insert(match_evaluations).values(user_id=user_id, job_posting_id=posting_id, model_version_id=rule_v1,
                                                    status="completed", score=Decimal("100.01")))
