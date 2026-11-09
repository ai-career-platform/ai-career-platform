"""T17 직무·기술 조회 서비스. HTTP·DB 수명주기와 무관하다.

페이지네이션 (API_CONTRACT §1.5)
- 직무 목록은 (name, job_role_id) keyset. 같은 조건이면 항상 같은 순서다.
- cursor = base64url(HMAC-SHA256 32바이트 + JSON[버전, 검색어 해시, 기준 이름 해시, 기준 id]).
  이름은 최대 160자라 그대로 넣으면 500자 제한을 넘을 수 있어 해시만 넣고,
  다음 요청에서 기준 직무의 이름을 다시 읽는다.
- 변조·다른 검색어·형식 오류, 기준 직무가 사라졌거나 이름이 바뀐 경우 400 INVALID_CURSOR.
  이름이 바뀐 채로 이어 읽으면 중간 항목이 조용히 빠지므로 처음부터 다시 조회하게 한다.
- 저장소(DB) 오류는 cursor 문제로 바꾸지 않고 그대로 올린다(503/500).
"""

import base64
import binascii
import hashlib
import hmac
import json
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    JobRoleDetail, JobRolePage, JobRoleQuery, SkillQuery, SkillSearchResult,
)

CURSOR_KEY_PURPOSE = "t17-job-roles-cursor-v1"
CURSOR_VERSION = 1
_SIG_LEN = 32


def _invalid_cursor(reason: str) -> AppError:
    return AppError(ErrorCode.INVALID_CURSOR, log_detail=f"job role cursor rejected: {reason}")


class CatalogService:
    def __init__(self, repository: CatalogRepository, *, cursor_key: bytes):
        if not isinstance(cursor_key, bytes) or len(cursor_key) < _SIG_LEN:
            raise ValueError("cursor_key must contain at least 32 bytes")
        self.repository = repository
        self._cursor_key = cursor_key

    @staticmethod
    def _digest(value: str | None) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()

    def _encode_cursor(self, q: str | None, name: str, role_id: UUID) -> str:
        payload = json.dumps(
            [CURSOR_VERSION, self._digest(q), self._digest(name), str(role_id)], separators=(",", ":"),
        ).encode()
        signature = hmac.digest(self._cursor_key, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    def _parse_cursor(self, token: str, q: str | None) -> tuple[str, UUID]:
        """서명·형식·검색어만 확인한다. DB는 읽지 않는다. 반환: (기준 이름 해시, 기준 id)."""
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            # 같은 바이트의 다른 Base64 표기(패딩 등)는 발급한 cursor가 아니다.
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
                raise ValueError("non-canonical encoding")
            signature, payload = raw[:_SIG_LEN], raw[_SIG_LEN:]
            if not hmac.compare_digest(signature, hmac.digest(self._cursor_key, payload, "sha256")):
                raise ValueError("bad signature")
            version, q_hash, name_hash, role_id = json.loads(payload)
            if type(version) is not int or version != CURSOR_VERSION or q_hash != self._digest(q):
                raise ValueError("cursor does not match this query")
            return name_hash, UUID(role_id)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise _invalid_cursor(type(exc).__name__) from None

    def _anchor(self, token: str, q: str | None) -> tuple[str, UUID]:
        name_hash, role_id = self._parse_cursor(token, q)
        name = self.repository.job_role_name(role_id)
        if name is None or self._digest(name) != name_hash:
            raise _invalid_cursor("anchor missing or renamed")
        return name, role_id

    def list_job_roles(self, query: JobRoleQuery) -> JobRolePage:
        after = self._anchor(query.cursor, query.q) if query.cursor is not None else None
        # limit+1개를 읽어 다음 페이지가 있는지 판단한다.
        rows = self.repository.list_job_roles(q=query.q, after=after, limit=query.limit + 1)
        items = rows[:query.limit]
        more = len(rows) > query.limit
        return JobRolePage(
            items=items,
            next_cursor=self._encode_cursor(query.q, items[-1].name, items[-1].job_role_id) if more else None,
        )

    def get_job_role(self, role_id: UUID) -> JobRoleDetail:
        role = self.repository.get_job_role(role_id)
        if role is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job role missing")
        return role

    def search_skills(self, query: SkillQuery) -> SkillSearchResult:
        return SkillSearchResult(items=self.repository.search_skills(q=query.q, limit=query.limit))
