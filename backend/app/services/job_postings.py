"""T18 기업·채용공고 조회 서비스. HTTP·DB 수명주기와 무관하다.

페이지네이션 (API_CONTRACT §1.5)
- 정렬키 + id로 keyset 페이지네이션. 같은 조건이면 항상 같은 순서라 다음 페이지에 중복·누락이 없다.
- cursor = base64url(HMAC-SHA256 서명 32바이트 + JSON[버전, 목록 종류, 검색 조건 digest, 마지막 id]).
  서명이 틀리거나(변조), 다른 검색 조건에 쓰였거나, 기준 항목이 사라졌으면 400 INVALID_CURSOR.
- 서명 키는 새 환경변수를 만들지 않고 T15의 `JWT_SECRET`에서 용도별로 파생한다
  (HMAC(JWT_SECRET, "t18-list-cursor-v1")). 키가 바뀌면 이전 cursor만 무효가 된다.
"""

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.job_postings import JobPostingRepository, PostingFilter, PostingRow
from app.schemas.job_postings import (
    CompanyDetail, CompanyPage, CompanyRef, JobPostingDetail, JobPostingPage, JobPostingSummary, JobRoleRef,
    RequiredSkill, SkillRef,
)

CURSOR_VERSION = 1
_CURSOR_PURPOSE = b"t18-list-cursor-v1"
_SIG_LEN = 32


def derive_cursor_key(secret: str) -> bytes:
    return hmac.digest(secret.encode("utf-8"), _CURSOR_PURPOSE, "sha256")


class ListCursor:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("cursor key must be at least 32 bytes")
        self._key = key

    @staticmethod
    def _digest(kind: str, params: dict) -> str:
        raw = json.dumps([kind, params], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def encode(self, kind: str, params: dict, last_id: UUID) -> str:
        payload = json.dumps([CURSOR_VERSION, kind, self._digest(kind, params), str(last_id)],
                             separators=(",", ":")).encode()
        sig = hmac.digest(self._key, payload, "sha256")
        return base64.urlsafe_b64encode(sig + payload).decode().rstrip("=")

    def decode(self, token: str, kind: str, params: dict) -> UUID:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            sig, payload = raw[:_SIG_LEN], raw[_SIG_LEN:]
            if not hmac.compare_digest(sig, hmac.digest(self._key, payload, "sha256")):
                raise ValueError("bad signature")
            version, saved_kind, digest, last_id = json.loads(payload)
            if version != CURSOR_VERSION or saved_kind != kind or digest != self._digest(kind, params):
                raise ValueError("cursor does not match this query")
            return UUID(last_id)
        except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
            raise AppError(ErrorCode.INVALID_CURSOR, log_detail=f"cursor rejected: {type(exc).__name__}") from None


def _not_found(what: str) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, log_detail=f"{what} missing or not visible")


def _summary(row: PostingRow) -> dict:
    return dict(
        job_posting_id=row.job_posting_id, title=row.title, status=row.status,
        company=CompanyRef(company_id=row.company_id, name=row.company_name),
        job_role=None if row.job_role_id is None else JobRoleRef(
            job_role_id=row.job_role_id, code=row.job_role_code, name=row.job_role_name),
        employment_type=row.employment_type, location_text=row.location_text,
        published_at=row.published_at, expires_at=row.expires_at,
    )


class JobPostingService:
    def __init__(self, repo: JobPostingRepository, cursor: ListCursor, clock=lambda: datetime.now(UTC)) -> None:
        self._repo = repo
        self._cursor = cursor
        self._clock = clock

    # ---------------------------------------------------------------- companies
    def list_companies(self, q: str | None, limit: int, cursor: str | None) -> CompanyPage:
        params = {"q": q}
        after = self._cursor.decode(cursor, "companies", params) if cursor else None
        # limit+1개를 읽어 다음 페이지가 있는지 판단한다.
        rows = self._repo.list_companies(q, after, limit + 1)
        if rows is None:
            raise AppError(ErrorCode.INVALID_CURSOR, log_detail="company cursor anchor missing")
        page, more = rows[:limit], len(rows) > limit
        return CompanyPage(
            items=[CompanyRef(company_id=r.company_id, name=r.name) for r in page],
            next_cursor=self._cursor.encode("companies", params, page[-1].company_id) if more else None,
        )

    def get_company(self, company_id: UUID) -> CompanyDetail:
        row = self._repo.get_company(company_id, self._clock())
        if row is None:
            raise _not_found("company")
        return CompanyDetail(
            company_id=row.company_id, name=row.name, website_url=row.website_url, description=row.description,
            open_posting_count=row.open_posting_count, source=row.source_code,
        )

    # ---------------------------------------------------------------- postings
    def list_postings(self, f: PostingFilter, limit: int, cursor: str | None) -> JobPostingPage:
        params = {
            "q": f.q, "company_id": str(f.company_id) if f.company_id else None,
            "job_role_id": str(f.job_role_id) if f.job_role_id else None,
            "include_closed": f.include_closed, "sort": f.sort,
        }
        after = self._cursor.decode(cursor, "job_postings", params) if cursor else None
        rows = self._repo.list_postings(f, after, limit + 1, self._clock())
        if rows is None:
            raise AppError(ErrorCode.INVALID_CURSOR, log_detail="posting cursor anchor missing or hidden")
        page, more = rows[:limit], len(rows) > limit
        return JobPostingPage(
            items=[JobPostingSummary(**_summary(r)) for r in page],
            next_cursor=self._cursor.encode("job_postings", params, page[-1].job_posting_id) if more else None,
        )

    def get_posting(self, job_posting_id: UUID, user_id: UUID | None) -> JobPostingDetail:
        row = self._repo.get_posting(job_posting_id, self._clock())
        if row is None:
            raise _not_found("job posting")
        skills = [
            RequiredSkill(skill=SkillRef(skill_id=s.skill_id, code=s.code, name=s.name),
                          required_level=s.required_level, is_required=s.is_required)
            for s in self._repo.posting_skills(job_posting_id, row.job_role_id)
        ]
        return JobPostingDetail(
            **_summary(row), description=row.description, source_url=row.source_url, required_skills=skills,
            is_bookmarked=None if user_id is None else self._repo.is_bookmarked(user_id, job_posting_id),
        )
