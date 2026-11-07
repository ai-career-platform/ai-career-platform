"""T16 PostgreSQL 저장소·API 연동 테스트 — **일회용 로컬 DB 전용**.

실행 조건 (둘 다 없으면 전부 skip):
    T16_TEST_ONLY=YES
    T16_TEST_DATABASE_URL=postgresql://<user>@localhost:<port>/<db>   # 버려도 되는 DB만

`career` 스키마를 지우고 database/DATA_DICTIONARY.md에서 만든 검증용 DDL로 다시 만든다.
공용 Staging DB를 절대 가리키지 말 것.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import InvalidTokenError, get_token_verifier
from app.core.config import get_settings
from app.main import create_app
from app.repositories.user_profile_postgres import PostgresUserProfileRepository

DB_URL = os.environ.get("T16_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL or os.environ.get("T16_TEST_ONLY") != "YES",
    reason="T16_TEST_ONLY=YES and T16_TEST_DATABASE_URL (disposable DB) required",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = datetime(2026, 11, 6, 1, tzinfo=UTC)
ALICE = UUID("3f1b6c2e-6a4f-4f53-9a7e-0c2d1e5b7a10")
BOB = UUID("8d2e4a10-1b7c-4e2f-9c3d-5a6b7c8d9e0f")
GHOST = UUID("00000000-0000-4000-8000-000000000000")


def _ddl() -> str:
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "database/model/check_data_dictionary.py"), "--ddl"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
    )
    return out.stdout


def _committed(query: str, *params):
    """다른 연결로 읽는다 → 커밋된 값만 보인다."""
    with psycopg.connect(DB_URL, autocommit=True) as other:
        return other.execute(query, params).fetchall()


def _profile_row(user_id):
    rows = _committed("SELECT headline, bio, location_text FROM career.user_profiles WHERE user_id = %s", user_id)
    return rows[0] if rows else None


@pytest.fixture(scope="module")
def engine():
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS career CASCADE")
        conn.execute("CREATE SCHEMA career")
        conn.execute(_ddl())
    eng = create_engine(DB_URL.replace("postgresql://", "postgresql+psycopg://", 1))
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def seed(engine):
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE career.users CASCADE")
        conn.execute(
            """
            INSERT INTO career.users (user_id, email, email_canonical, display_name, created_at)
            VALUES (%s, 'alice@example.com', 'alice@example.com', '앨리스', %s),
                   (%s, 'bob@example.com', 'bob@example.com', '밥', %s)
            """,
            (ALICE, CREATED_AT, BOB, CREATED_AT),
        )
        conn.execute(
            "INSERT INTO career.user_profiles (user_id, headline, location_text) VALUES (%s, '백엔드 주니어', '서울')",
            (ALICE,),
        )


@pytest.fixture
def repo(engine):
    with Session(engine) as session:
        yield PostgresUserProfileRepository(session)


# ---- 저장소 ------------------------------------------------------------------


def test_get_user_with_profile(repo):
    record = repo.get(ALICE)
    assert record.display_name == "앨리스"
    assert (record.headline, record.bio, record.location_text) == ("백엔드 주니어", None, "서울")
    assert record.created_at == CREATED_AT


def test_get_user_without_profile_row(repo):
    record = repo.get(BOB)
    assert (record.headline, record.bio, record.location_text) == (None, None, None)


def test_get_missing_user(repo):
    assert repo.get(GHOST) is None


def test_update_changes_only_sent_columns_and_commits(repo):
    record = repo.update(ALICE, {"headline": "새 소개"})
    assert (record.headline, record.location_text) == ("새 소개", "서울")
    assert _profile_row(ALICE) == ("새 소개", None, "서울")


def test_update_null_clears_column(repo):
    repo.update(ALICE, {"location_text": None})
    assert _profile_row(ALICE) == ("백엔드 주니어", None, None)


def test_update_creates_profile_row_when_missing(repo):
    assert _profile_row(BOB) is None
    repo.update(BOB, {"bio": "안녕하세요"})
    assert _profile_row(BOB) == (None, "안녕하세요", None)


def test_update_display_name_bumps_updated_at(repo):
    (before,) = _committed("SELECT updated_at FROM career.users WHERE user_id = %s", ALICE)[0]
    record = repo.update(ALICE, {"display_name": "앨리스2"})
    (after,) = _committed("SELECT updated_at FROM career.users WHERE user_id = %s", ALICE)[0]
    assert record.display_name == "앨리스2"
    assert after > before


def test_update_missing_user_changes_nothing(repo):
    assert repo.update(GHOST, {"headline": "x"}) is None
    assert _committed("SELECT count(*) FROM career.user_profiles") == [(1,)]


def test_update_does_not_touch_other_user(repo):
    repo.update(BOB, {"headline": "밥 소개"})
    assert _profile_row(ALICE) == ("백엔드 주니어", None, "서울")


def test_update_rejects_unknown_column(repo):
    with pytest.raises(ValueError):
        repo.update(ALICE, {"email": "x@example.com"})


def test_db_check_rolls_back_whole_update(repo):
    """API 검증을 우회해도 DB CHECK(bio ≤ 5000)가 막고, 같은 요청의 다른 변경도 남지 않는다."""
    with pytest.raises(IntegrityError):
        repo.update(ALICE, {"display_name": "바뀌면 안 됨", "bio": "가" * 5001})
    assert _committed("SELECT display_name FROM career.users WHERE user_id = %s", ALICE) == [("앨리스",)]
    assert repo.get(ALICE).display_name == "앨리스"  # 롤백 뒤 같은 세션도 계속 사용 가능


# ---- API: 실제 get_db(T14) 경로 ----------------------------------------------------


@pytest.fixture
def api(monkeypatch, engine):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    app = create_app()

    def verifier(token: str) -> UUID:
        tokens = {"token-alice": ALICE, "token-bob": BOB, "token-ghost": GHOST}
        if token not in tokens:
            raise InvalidTokenError
        return tokens[token]

    # 인증(T15)만 테스트용으로 바꾸고, 저장소는 실제 get_db → PostgresUserProfileRepository를 쓴다.
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_api_get_me_reads_postgres(api):
    response = api.get("/api/v1/me", headers={"Authorization": "Bearer token-alice"})
    assert response.status_code == 200
    assert response.json()["profile"] == {"headline": "백엔드 주니어", "bio": None, "location_text": "서울"}


def test_api_patch_then_get_through_postgres(api):
    headers = {"Authorization": "Bearer token-bob"}
    patched = api.patch("/api/v1/me", headers=headers, json={"display_name": "밥2", "headline": "신입", "bio": None})
    assert patched.status_code == 200
    fetched = api.get("/api/v1/me", headers=headers)
    assert fetched.json()["display_name"] == "밥2"
    assert fetched.json()["profile"] == {"headline": "신입", "bio": None, "location_text": None}
    assert _profile_row(BOB) == ("신입", None, None)


def test_api_unknown_user_returns_404(api):
    response = api.get("/api/v1/me", headers={"Authorization": "Bearer token-ghost"})
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_api_invalid_patch_writes_nothing(api):
    response = api.patch("/api/v1/me", headers={"Authorization": "Bearer token-alice"}, json={"bio": "가" * 5001})
    assert response.status_code == 422
    assert _profile_row(ALICE) == ("백엔드 주니어", None, "서울")
