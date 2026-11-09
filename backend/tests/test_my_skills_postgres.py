"""T33 PostgreSQL 통합 테스트 (선택 실행) — T05 검증용 DDL + T10 Seed 위에서 GET/PUT /me/skills.

`T15_TEST_DATABASE_URL`을 지정했을 때만 실행한다(T15 통합 테스트와 같은 일회용 DB 사용).
지정한 DB의 `career` 스키마를 지우고 다시 만들므로 **일회용 로컬 DB에서만** 쓴다. 공유 Staging DB 주소 금지.

    $env:T15_TEST_DATABASE_URL = "postgresql://postgres:t15local@127.0.0.1:55432/postgres"
    .venv\\Scripts\\python.exe -m pytest tests/test_my_skills_postgres.py -v
"""

import time
import uuid

import jwt
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import API_V1_PREFIX
from app.repositories.catalog import skills
from app.repositories.my_skills import user_skills
from tests.conftest import bearer
from tests.test_auth_postgres import CONSENTS, engine, pg_client, pytestmark  # noqa: F401  (픽스처·skip 조건 재사용)

URL = f"{API_V1_PREFIX}/me/skills"


def signup(client, email):
    r = client.post(f"{API_V1_PREFIX}/auth/signup", json={
        "email": email, "password": "correct-horse-battery-1", "display_name": "기술", "consents": CONSENTS,
    })
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return bearer(token), uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"])


def seed_skills(engine, n):
    with Session(engine) as db:
        return list(db.scalars(select(skills.c.skill_id).where(skills.c.is_active.is_(True)).order_by(skills.c.code).limit(n)))


def stored(engine, user_id):
    with Session(engine) as db:
        rows = db.execute(
            select(user_skills.c.skill_id, user_skills.c.proficiency, user_skills.c.created_at, user_skills.c.updated_at)
            .where(user_skills.c.user_id == user_id)
        ).all()
    return {r.skill_id: r for r in rows}


def test_replace_and_list_against_postgres(pg_client, engine):  # noqa: F811
    headers, user_id = signup(pg_client, "skills@example.com")
    a, b, c = seed_skills(engine, 3)

    r = pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 2}, {"skill_id": str(b)}]}, headers=headers)
    assert r.status_code == 200, r.text
    assert {(s["skill"]["skill_id"], s["proficiency"]) for s in r.json()} == {(str(a), 2), (str(b), None)}
    first = stored(engine, user_id)

    time.sleep(0.01)
    r = pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 4}, {"skill_id": str(c), "proficiency": 1}]},
                      headers=headers)
    assert r.status_code == 200, r.text
    second = stored(engine, user_id)
    assert set(second) == {a, c}  # b 삭제, c 추가
    assert second[a].proficiency == 4
    assert second[a].created_at == first[a].created_at and second[a].updated_at > first[a].updated_at

    # 같은 숙련도로 다시 저장하면 updated_at 그대로
    pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 4}, {"skill_id": str(c), "proficiency": 1}]},
                  headers=headers)
    assert stored(engine, user_id)[a].updated_at == second[a].updated_at

    # 응답 정렬: 이름, skill_id
    names = [s["skill"]["name"] for s in pg_client.get(URL, headers=headers).json()]
    assert names == sorted(names)

    # 빈 목록 → 전부 삭제
    assert pg_client.put(URL, json={"items": []}, headers=headers).json() == []
    assert stored(engine, user_id) == {}


def test_rejections_change_nothing_against_postgres(pg_client, engine):  # noqa: F811
    headers, user_id = signup(pg_client, "reject@example.com")
    a, b = seed_skills(engine, 2)
    pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 3}]}, headers=headers)
    before = stored(engine, user_id)

    dup = pg_client.put(URL, json={"items": [{"skill_id": str(b)}, {"skill_id": str(b)}]}, headers=headers)
    assert dup.status_code == 422 and dup.json()["code"] == "DUPLICATE_SKILL"
    unknown = pg_client.put(URL, json={"items": [{"skill_id": str(uuid.uuid4())}]}, headers=headers)
    assert unknown.status_code == 422 and unknown.json()["code"] == "VALIDATION_FAILED"
    assert stored(engine, user_id) == before


def test_retired_skill_rules_against_postgres(pg_client, engine):  # noqa: F811
    headers, _ = signup(pg_client, "retired@example.com")
    a, b = seed_skills(engine, 2)
    pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 2}]}, headers=headers)
    with Session(engine) as db, db.begin():
        db.execute(text("UPDATE career.skills SET is_active = false WHERE skill_id IN (:a, :b)"), {"a": a, "b": b})

    keep = pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 5}]}, headers=headers)
    assert keep.status_code == 200 and keep.json()[0]["proficiency"] == 5  # 이미 보유한 폐기 기술은 유지 가능
    add = pg_client.put(URL, json={"items": [{"skill_id": str(a)}, {"skill_id": str(b)}]}, headers=headers)
    assert add.status_code == 422  # 보유하지 않은 폐기 기술은 새로 추가 불가


def test_users_are_isolated_against_postgres(pg_client, engine):  # noqa: F811
    h1, u1 = signup(pg_client, "one@example.com")
    h2, u2 = signup(pg_client, "two@example.com")
    a, b = seed_skills(engine, 2)
    pg_client.put(URL, json={"items": [{"skill_id": str(a), "proficiency": 1}]}, headers=h1)
    pg_client.put(URL, json={"items": [{"skill_id": str(b), "proficiency": 2}]}, headers=h2)
    pg_client.put(URL, json={"items": []}, headers=h2)
    assert set(stored(engine, u1)) == {a} and stored(engine, u2) == {}
