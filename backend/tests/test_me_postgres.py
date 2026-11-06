"""T16 PostgreSQL 저장소 테스트 — **일회용 로컬 DB 전용**.

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

import pytest

psycopg = pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.auth import InvalidTokenError, get_token_verifier  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.user_profile_postgres import PostgresUserProfileRepository  # noqa: E402
from app.routers.me import get_user_profile_repository  # noqa: E402

DB_URL = os.environ.get("T16_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL or os.environ.get("T16_TEST_ONLY") != "YES",
    reason="T16_TEST_ONLY=YES and T16_TEST_DATABASE_URL (disposable DB) required",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
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


@pytest.fixture(scope="module")
def schema():
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS career CASCADE")
        conn.execute("CREATE SCHEMA career")
        conn.execute(_ddl())
    yield


@pytest.fixture
def conn(schema):
    with psycopg.connect(DB_URL) as connection:
        with connection.transaction():
            connection.execute("TRUNCATE career.users CASCADE")
            connection.execute(
                """
                INSERT INTO career.users (user_id, email, email_canonical, display_name, created_at)
                VALUES (%s, 'alice@example.com', 'alice@example.com', '앨리스', %s),
                       (%s, 'bob@example.com', 'bob@example.com', '밥', %s)
                """,
                (ALICE, datetime(2026, 11, 6, 1, tzinfo=UTC), BOB, datetime(2026, 11, 6, 1, tzinfo=UTC)),
            )
            connection.execute(
                "INSERT INTO career.user_profiles (user_id, headline, location_text) VALUES (%s, '백엔드 주니어', '서울')",
                (ALICE,),
            )
        yield connection


@pytest.fixture
def repo(conn):
    return PostgresUserProfileRepository(conn)


def _profile_row(conn, user_id):
    return conn.execute(
        "SELECT headline, bio, location_text FROM career.user_profiles WHERE user_id = %s", (user_id,)
    ).fetchone()


# ---- 저장소 ------------------------------------------------------------------


def test_get_user_with_profile(repo):
    record = repo.get(ALICE)
    assert record.display_name == "앨리스"
    assert (record.headline, record.bio, record.location_text) == ("백엔드 주니어", None, "서울")
    assert record.created_at == datetime(2026, 11, 6, 1, tzinfo=UTC)


def test_get_user_without_profile_row(repo):
    record = repo.get(BOB)
    assert (record.headline, record.bio, record.location_text) == (None, None, None)


def test_get_missing_user(repo):
    assert repo.get(GHOST) is None


def test_update_changes_only_sent_columns(repo, conn):
    record = repo.update(ALICE, {"headline": "새 소개"})
    assert record.headline == "새 소개"
    assert record.location_text == "서울"
    assert _profile_row(conn, ALICE) == ("새 소개", None, "서울")


def test_update_null_clears_column(repo, conn):
    repo.update(ALICE, {"location_text": None})
    assert _profile_row(conn, ALICE) == ("백엔드 주니어", None, None)


def test_update_creates_profile_row_when_missing(repo, conn):
    assert _profile_row(conn, BOB) is None
    repo.update(BOB, {"bio": "안녕하세요"})
    assert _profile_row(conn, BOB) == (None, "안녕하세요", None)


def test_update_display_name_bumps_updated_at(repo, conn):
    before = conn.execute("SELECT updated_at FROM career.users WHERE user_id = %s", (ALICE,)).fetchone()[0]
    conn.commit()
    record = repo.update(ALICE, {"display_name": "앨리스2"})
    after = conn.execute("SELECT updated_at FROM career.users WHERE user_id = %s", (ALICE,)).fetchone()[0]
    assert record.display_name == "앨리스2"
    assert after > before


def test_update_is_committed(repo):
    repo.update(BOB, {"headline": "커밋 확인"})
    with psycopg.connect(DB_URL) as other:
        row = other.execute("SELECT headline FROM career.user_profiles WHERE user_id = %s", (BOB,)).fetchone()
    assert row == ("커밋 확인",)


def test_update_missing_user_changes_nothing(repo, conn):
    assert repo.update(GHOST, {"headline": "x"}) is None
    assert conn.execute("SELECT count(*) FROM career.user_profiles").fetchone()[0] == 1


def test_update_does_not_touch_other_user(repo, conn):
    repo.update(BOB, {"headline": "밥 소개"})
    assert _profile_row(conn, ALICE) == ("백엔드 주니어", None, "서울")


def test_update_rejects_unknown_column(repo):
    with pytest.raises(ValueError):
        repo.update(ALICE, {"email": "x@example.com"})


def test_db_check_rolls_back_whole_update(repo, conn):
    """API 검증을 우회해도 DB CHECK(bio ≤ 5000)가 막고, 같은 요청의 다른 변경도 남지 않는다."""
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.update(ALICE, {"display_name": "바뀌면 안 됨", "bio": "가" * 5001})
    conn.rollback()
    assert repo.get(ALICE).display_name == "앨리스"


# ---- API 끝까지 -----------------------------------------------------------------


def test_api_patch_then_get_through_postgres(conn):
    app = create_app()

    def verifier(token: str) -> UUID:
        if token != "token-bob":
            raise InvalidTokenError
        return BOB

    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_user_profile_repository] = lambda: PostgresUserProfileRepository(conn)
    headers = {"Authorization": "Bearer token-bob"}
    with TestClient(app) as client:
        patched = client.patch(
            "/api/v1/me", headers=headers, json={"display_name": "밥2", "headline": "신입", "bio": None}
        )
        fetched = client.get("/api/v1/me", headers=headers)
    assert patched.status_code == 200
    assert fetched.json()["display_name"] == "밥2"
    assert fetched.json()["profile"] == {"headline": "신입", "bio": None, "location_text": None}
