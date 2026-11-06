"""T16 `/api/v1/me` 테스트.

실제 JWT(T15)와 DB(T14)가 없으므로 토큰 검증기와 저장소를 테스트용으로 바꿔 끼운다.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.auth import InvalidTokenError, get_token_verifier
from app.core.config import get_settings
from app.core.errors import ERROR_CATALOG, ErrorCode
from app.main import create_app
from app.repositories.user_profile import InMemoryUserProfileRepository, UserProfileRecord
from app.routers.me import get_user_profile_repository

ALICE_ID = UUID("3f1b6c2e-6a4f-4f53-9a7e-0c2d1e5b7a10")
BOB_ID = UUID("8d2e4a10-1b7c-4e2f-9c3d-5a6b7c8d9e0f")
GHOST_ID = UUID("00000000-0000-4000-8000-000000000000")
CREATED_AT = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)

# 테스트 전용 가짜 토큰 → 사용자 매핑 (실제 비밀값 아님)
TOKENS = {"token-alice": ALICE_ID, "token-bob": BOB_ID, "token-ghost": GHOST_ID}


def fake_verifier(token: str) -> UUID:
    try:
        return TOKENS[token]
    except KeyError:
        raise InvalidTokenError from None


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_error(response, code: ErrorCode) -> None:
    """공통 에러 계약 {code, status, message} (T06 #41)."""
    spec = ERROR_CATALOG[code]
    assert response.status_code == spec.status
    assert response.json() == {"code": code, "status": spec.status, "message": spec.message}


@pytest.fixture
def repository():
    repo = InMemoryUserProfileRepository()
    repo.add(
        UserProfileRecord(
            user_id=ALICE_ID,
            email="alice@example.com",
            display_name="앨리스",
            status="active",
            created_at=CREATED_AT,
            headline="백엔드 주니어",
            bio=None,
            location_text="서울",
        )
    )
    # 프로필 행이 아직 없는 사용자
    repo.add(
        UserProfileRecord(
            user_id=BOB_ID,
            email="bob@example.com",
            display_name="밥",
            status="active",
            created_at=CREATED_AT,
        )
    )
    return repo


@pytest.fixture
def client(repository):
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_token_verifier] = lambda: fake_verifier
    app.dependency_overrides[get_user_profile_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


# ---- 조회 -------------------------------------------------------------------


def test_get_me_returns_contract_shape(client):
    response = client.get("/api/v1/me", headers=auth("token-alice"))
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(ALICE_ID),
        "email": "alice@example.com",
        "display_name": "앨리스",
        "status": "active",
        "profile": {"headline": "백엔드 주니어", "bio": None, "location_text": "서울"},
        "created_at": "2026-11-06T01:00:00Z",
    }


def test_get_me_without_profile_row_returns_null_profile_fields(client):
    response = client.get("/api/v1/me", headers=auth("token-bob"))
    assert response.status_code == 200
    assert response.json()["profile"] == {"headline": None, "bio": None, "location_text": None}


def test_get_me_unknown_user_returns_404(client):
    response = client.get("/api/v1/me", headers=auth("token-ghost"))
    assert_error(response, ErrorCode.NOT_FOUND)


# ---- 인증 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-real-token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "token-alice"},
    ],
)
@pytest.mark.parametrize("method", ["get", "patch"])
def test_missing_or_invalid_token_returns_401(client, method, headers):
    response = client.request(method, "/api/v1/me", headers=headers, json={"headline": "x"})
    assert_error(response, ErrorCode.UNAUTHENTICATED)
    assert response.headers["www-authenticate"] == "Bearer"


def test_default_verifier_rejects_every_token_until_t15(repository):
    app = create_app()
    app.dependency_overrides[get_user_profile_repository] = lambda: repository
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/me", headers=auth("token-alice"))
    assert_error(response, ErrorCode.UNAUTHENTICATED)


def test_default_repository_is_not_configured_until_t14():
    app = create_app()
    app.dependency_overrides[get_token_verifier] = lambda: fake_verifier
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/me", headers=auth("token-alice"))
    assert_error(response, ErrorCode.DEPENDENCY_UNAVAILABLE)


# ---- 소유권 -----------------------------------------------------------------


def test_user_id_in_query_is_ignored(client):
    response = client.get(f"/api/v1/me?user_id={BOB_ID}", headers=auth("token-alice"))
    assert response.status_code == 200
    assert response.json()["user_id"] == str(ALICE_ID)


def test_user_id_in_patch_body_is_rejected_and_nothing_changes(client, repository):
    response = client.patch(
        "/api/v1/me",
        headers=auth("token-alice"),
        json={"user_id": str(BOB_ID), "display_name": "해킹"},
    )
    assert_error(response, ErrorCode.VALIDATION_FAILED)
    assert repository.get(BOB_ID).display_name == "밥"
    assert repository.get(ALICE_ID).display_name == "앨리스"


def test_patch_changes_only_the_token_owner(client, repository):
    response = client.patch("/api/v1/me", headers=auth("token-alice"), json={"headline": "새 소개"})
    assert response.status_code == 200
    assert repository.get(ALICE_ID).headline == "새 소개"
    assert repository.get(BOB_ID).headline is None


def test_no_path_for_other_users_profile(client):
    response = client.get(f"/api/v1/me/{BOB_ID}", headers=auth("token-alice"))
    assert response.status_code in (404, 405)
    assert response.json()["code"] in ("NOT_FOUND", "METHOD_NOT_ALLOWED")


# ---- 부분 수정 ----------------------------------------------------------------


def test_patch_changes_only_sent_fields(client):
    response = client.patch(
        "/api/v1/me",
        headers=auth("token-alice"),
        json={"headline": "백엔드 개발자 지망", "location_text": "부산"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "앨리스"
    assert body["profile"] == {"headline": "백엔드 개발자 지망", "bio": None, "location_text": "부산"}


def test_patch_null_clears_value_and_omitted_keeps_value(client):
    response = client.patch("/api/v1/me", headers=auth("token-alice"), json={"headline": None})
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["headline"] is None
    assert profile["location_text"] == "서울"


def test_patch_creates_profile_values_for_user_without_profile_row(client):
    response = client.patch("/api/v1/me", headers=auth("token-bob"), json={"bio": "안녕하세요"})
    assert response.status_code == 200
    assert response.json()["profile"]["bio"] == "안녕하세요"


def test_patch_display_name(client):
    response = client.patch("/api/v1/me", headers=auth("token-alice"), json={"display_name": "앨리스2"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "앨리스2"


def test_patch_accepts_max_lengths(client):
    payload = {
        "display_name": "가" * 100,
        "headline": "가" * 200,
        "bio": "가" * 5000,
        "location_text": "가" * 120,
    }
    response = client.patch("/api/v1/me", headers=auth("token-alice"), json=payload)
    assert response.status_code == 200


def test_patch_unknown_user_returns_404(client):
    response = client.patch("/api/v1/me", headers=auth("token-ghost"), json={"headline": "x"})
    assert_error(response, ErrorCode.NOT_FOUND)


# ---- 422 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"display_name": None},
        {"display_name": ""},
        {"display_name": "   "},
        {"display_name": "가" * 101},
        {"headline": "가" * 201},
        {"bio": "가" * 5001},
        {"location_text": "가" * 121},
        {"headline": 123},
        {"email": "new@example.com"},
        {"status": "disabled"},
        {"nickname": "x"},
    ],
)
def test_patch_invalid_payload_returns_422_and_changes_nothing(client, repository, payload):
    before = repository.get(ALICE_ID)
    response = client.patch("/api/v1/me", headers=auth("token-alice"), json=payload)
    assert_error(response, ErrorCode.VALIDATION_FAILED)
    assert repository.get(ALICE_ID) == before


def test_patch_non_object_body_returns_422(client):
    response = client.patch("/api/v1/me", headers=auth("token-alice"), json=["headline"])
    assert_error(response, ErrorCode.VALIDATION_FAILED)


# ---- OpenAPI -----------------------------------------------------------------


def test_openapi_lists_me_operations(client):
    spec = client.get("/openapi.json").json()
    assert set(spec["paths"]["/api/v1/me"]) == {"get", "patch"}
    patch_schema = spec["components"]["schemas"]["MePatch"]
    assert patch_schema["additionalProperties"] is False
    assert "user_id" not in patch_schema["properties"]
    get_responses = spec["paths"]["/api/v1/me"]["get"]["responses"]
    for status in ("401", "404", "422", "500", "503"):
        assert get_responses[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
