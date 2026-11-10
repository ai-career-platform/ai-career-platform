"""T86 문서 보안 — T49 시험(tests/test_documents.py, test_documents_e2e.py)이 다루지 않던 경계만 추가합니다.

이미 있는 것(중복 작성 안 함): 확장자·MIME·시그니처·크기 초과·파일명 경로(`../x.pdf`)·빈 파일·업로드 실패 후 잔여 파일·
다른 사용자 조회·다운로드·삭제·인증 선행·심볼릭 링크·디렉터리 권한.
여기서 추가: 문서 ID 자리의 경로 탐색·비 UUID, 클라이언트가 소유자를 지정하려는 시도, 목록의 user_id 질의, 잘못된 요청 Content-Type.
기존 `docs` fixture(격리 SQLite + 임시 디렉터리 저장소)를 재사용합니다. 디렉터리 0700 검사 때문에 POSIX(Linux CI)에서 실행됩니다.
"""
import uuid

import jwt
import pytest

from tests.test_documents import BASE, docs, login, owner, upload  # noqa: F401  (fixture 재사용)

TRAVERSAL_IDS = ["..%2F..%2Fetc%2Fpasswd", "%2e%2e%2f%2e%2e%2fhealth", "....//....//etc", "not-a-uuid",
                 "00000000-0000-0000-0000-00000000000g", "%00", "1%27%20OR%20%271%27%3D%271"]


def user_id_of(headers) -> uuid.UUID:
    return uuid.UUID(jwt.decode(headers["Authorization"][7:], options={"verify_signature": False})["sub"])


@pytest.mark.parametrize("doc_id", TRAVERSAL_IDS)
def test_document_id_traversal_and_malformed_ids_never_reach_storage(client, docs, doc_id):
    a, _ = login(client)
    assert upload(client, a).status_code == 201
    for method, suffix in (("GET", ""), ("GET", "/file"), ("DELETE", "")):
        response = client.request(method, f"{BASE}/{doc_id}{suffix}", headers=a)
        assert response.status_code in (404, 422), f"{method} {doc_id}{suffix}: {response.status_code}"
        assert b"root:" not in response.content and b"%PDF" not in response.content
    assert len(client.get(BASE, headers=a).json()["items"]) == 1, "nothing deleted"


def test_client_cannot_choose_the_document_owner(client, docs):
    a, _ = login(client)
    b, _ = login(client, "t86-doc-b@example.com")
    victim = str(user_id_of(b))
    response = client.post(BASE, headers=a, data={"kind": "resume", "owner_user_id": victim, "user_id": victim},
                           files={"file": ("x.pdf", b"%PDF-1.7\nsynthetic\n%%EOF", "application/pdf")},
                           params={"user_id": victim})
    # 안전한 결과는 두 가지뿐: 알 수 없는 필드를 거부(422)하거나, 무시하고 업로드한 사람을 소유자로 저장(201)
    assert response.status_code in (201, 422), response.text
    if response.status_code == 201:
        assert owner(docs, response.json()["document_id"]) == user_id_of(a)
    assert client.get(BASE, headers=b).json()["items"] == []


def test_list_ignores_a_user_id_query(client, docs):
    a, _ = login(client)
    upload(client, a)
    b, _ = login(client, "t86-doc-c@example.com")
    response = client.get(BASE, headers=b, params={"user_id": str(user_id_of(a)), "owner_user_id": str(user_id_of(a))})
    assert response.status_code in (200, 422)
    assert response.status_code == 422 or response.json()["items"] == []


@pytest.mark.parametrize("kwargs", [
    {"json": {"kind": "resume", "file": "JVBERi0xLjcK"}},
    {"content": b"%PDF-1.7\n", "headers_extra": {"Content-Type": "application/pdf"}},
    {"content": b"kind=resume", "headers_extra": {"Content-Type": "application/x-www-form-urlencoded"}},
])
def test_wrong_request_content_type_is_rejected_without_files(client, docs, kwargs):
    a, _ = login(client)
    extra = kwargs.pop("headers_extra", {})
    response = client.post(BASE, headers={**a, **extra}, **kwargs)
    assert response.status_code in (400, 415, 422), response.status_code
    assert not list(docs.storage.root.iterdir())
    assert client.get(BASE, headers=a).json()["items"] == []
