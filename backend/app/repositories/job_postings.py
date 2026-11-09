"""T18 기업·채용공고 읽기 전용 DB 접근 (스키마 `career`, database/DATA_DICTIONARY.md 기준).

- 서비스는 `JobPostingRepository` 프로토콜에만 의존한다. 테스트는 메모리 구현을 쓴다.
- 공유 ORM 모델을 새로 만들지 않고, 사용하는 컬럼만 `table()`로 적는다(T17과 같은 방식).
  테이블 생성·Migration은 T09 범위이며 여기서는 SELECT만 한다.
- "게시 중" = status='published' 이고 (expires_at 없음 또는 now 이후).
  status='published'라도 마감일이 지나면 응답 status는 'closed'로 보인다.
- draft 공고는 어떤 경로로도 나가지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Integer, String, Uuid, and_, case, column, exists, func, literal, or_, select, table, tuple_,
)
from sqlalchemy.orm import Session

VISIBLE_STATUSES = ("published", "closed")


@dataclass(frozen=True)
class CompanyRow:
    company_id: UUID
    name: str


@dataclass(frozen=True)
class CompanyDetailRow:
    company_id: UUID
    name: str
    website_url: str | None
    description: str | None
    source_code: str
    open_posting_count: int


@dataclass(frozen=True)
class PostingRow:
    job_posting_id: UUID
    title: str
    status: str  # 화면에 보일 상태 (published | closed)
    company_id: UUID
    company_name: str
    job_role_id: UUID | None
    job_role_code: str | None
    job_role_name: str | None
    employment_type: str | None
    location_text: str | None
    published_at: datetime | None
    expires_at: datetime | None
    description: str | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class PostingSkillRow:
    skill_id: UUID
    code: str
    name: str
    required_level: int | None
    is_required: bool


@dataclass(frozen=True)
class PostingFilter:
    q: str | None
    company_id: UUID | None
    job_role_id: UUID | None
    include_closed: bool
    sort: str  # "-published_at" | "expires_at"


class JobPostingRepository(Protocol):
    def list_companies(self, q: str | None, after: UUID | None, limit: int) -> list[CompanyRow] | None:
        """after 기업이 없으면 None (cursor 무효)."""

    def get_company(self, company_id: UUID, now: datetime) -> CompanyDetailRow | None: ...

    def list_postings(
        self, f: PostingFilter, after: UUID | None, limit: int, now: datetime
    ) -> list[PostingRow] | None:
        """after 공고가 없거나 현재 조건에 맞지 않으면 None (cursor 무효)."""

    def get_posting(self, job_posting_id: UUID, now: datetime) -> PostingRow | None: ...

    def posting_skills(self, job_posting_id: UUID, job_role_id: UUID | None) -> list[PostingSkillRow]: ...

    def is_bookmarked(self, user_id: UUID, job_posting_id: UUID) -> bool: ...


_SCHEMA = "career"
data_sources = table("data_sources", column("source_id", Uuid), column("code", String), schema=_SCHEMA)
companies = table(
    "companies", column("company_id", Uuid), column("name", String), column("website_url", String),
    column("description", String), column("source_id", Uuid), schema=_SCHEMA,
)
job_roles = table("job_roles", column("job_role_id", Uuid), column("code", String), column("name", String),
                  schema=_SCHEMA)
skills = table("skills", column("skill_id", Uuid), column("code", String), column("name", String), schema=_SCHEMA)
job_role_skills = table("job_role_skills", column("job_role_id", Uuid), column("skill_id", Uuid),
                        column("required_level", Integer), schema=_SCHEMA)
job_postings = table(
    "job_postings", column("job_posting_id", Uuid), column("company_id", Uuid), column("job_role_id", Uuid),
    column("title", String), column("description", String), column("employment_type", String),
    column("location_text", String), column("source_url", String), column("status", String),
    column("published_at", DateTime(timezone=True)), column("expires_at", DateTime(timezone=True)),
    schema=_SCHEMA,
)
job_posting_skills = table("job_posting_skills", column("job_posting_id", Uuid), column("skill_id", Uuid),
                           column("is_required", Boolean), column("required_level", Integer), schema=_SCHEMA)
user_job_bookmarks = table("user_job_bookmarks", column("user_id", Uuid), column("job_posting_id", Uuid),
                           schema=_SCHEMA)

_NEG_INF = literal("-infinity").cast(DateTime(timezone=True))
_POS_INF = literal("infinity").cast(DateTime(timezone=True))


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains(col, q: str):
    return col.ilike(f"%{escape_like(q)}%", escape="\\")


def _is_open(now: datetime):
    p = job_postings.c
    return and_(p.status == "published", or_(p.expires_at.is_(None), p.expires_at > now))


def _display_status(now: datetime):
    p = job_postings.c
    return case(
        (and_(p.status == "published", p.expires_at.is_not(None), p.expires_at <= now), literal("closed")),
        else_=p.status,
    )


class SqlJobPostingRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    # ---------------------------------------------------------------- companies
    def list_companies(self, q: str | None, after: UUID | None, limit: int) -> list[CompanyRow] | None:
        c = companies.c
        key = func.lower(c.name)  # ix_companies_1 (lower(name))
        stmt = select(c.company_id, c.name).order_by(key, c.company_id).limit(limit)
        if q:
            stmt = stmt.where(_contains(c.name, q))
        if after is not None:
            anchor = self._db.execute(select(key).where(c.company_id == after)).scalar_one_or_none()
            if anchor is None:
                return None
            stmt = stmt.where(tuple_(key, c.company_id) > tuple_(literal(anchor), literal(after, Uuid)))
        return [CompanyRow(r.company_id, r.name) for r in self._db.execute(stmt)]

    def get_company(self, company_id: UUID, now: datetime) -> CompanyDetailRow | None:
        c, p = companies.c, job_postings.c
        open_count = (
            select(func.count()).select_from(job_postings)
            .where(p.company_id == c.company_id, _is_open(now)).scalar_subquery()
        )
        row = self._db.execute(
            select(c.company_id, c.name, c.website_url, c.description, data_sources.c.code, open_count.label("n"))
            .join(data_sources, data_sources.c.source_id == c.source_id)
            .where(c.company_id == company_id)
        ).one_or_none()
        if row is None:
            return None
        return CompanyDetailRow(row.company_id, row.name, row.website_url, row.description, row.code, int(row.n))

    # ---------------------------------------------------------------- postings
    def _posting_select(self, now: datetime, *, detail: bool = False):
        p, c, r = job_postings.c, companies.c, job_roles.c
        cols = [
            p.job_posting_id, p.title, _display_status(now).label("display_status"),
            c.company_id, c.name.label("company_name"),
            r.job_role_id, r.code.label("job_role_code"), r.name.label("job_role_name"),
            p.employment_type, p.location_text, p.published_at, p.expires_at,
        ]
        if detail:
            cols += [p.description, p.source_url]
        return (
            select(*cols)
            .select_from(job_postings)
            .join(companies, c.company_id == p.company_id)
            .outerjoin(job_roles, r.job_role_id == p.job_role_id)
        )

    @staticmethod
    def _row(row, *, detail: bool = False) -> PostingRow:
        return PostingRow(
            job_posting_id=row.job_posting_id, title=row.title, status=row.display_status,
            company_id=row.company_id, company_name=row.company_name,
            job_role_id=row.job_role_id, job_role_code=row.job_role_code, job_role_name=row.job_role_name,
            employment_type=row.employment_type, location_text=row.location_text,
            published_at=row.published_at, expires_at=row.expires_at,
            description=row.description if detail else None, source_url=row.source_url if detail else None,
        )

    def _visibility(self, f: PostingFilter, now: datetime):
        p = job_postings.c
        conds = [_is_open(now) if not f.include_closed else p.status.in_(VISIBLE_STATUSES)]
        if f.q:
            conds.append(_contains(p.title, f.q))
        if f.company_id is not None:
            conds.append(p.company_id == f.company_id)
        if f.job_role_id is not None:
            conds.append(p.job_role_id == f.job_role_id)
        return and_(*conds)

    def list_postings(
        self, f: PostingFilter, after: UUID | None, limit: int, now: datetime
    ) -> list[PostingRow] | None:
        p = job_postings.c
        visible = self._visibility(f, now)
        if f.sort == "expires_at":
            # 마감 임박순. 마감일 없는 공고는 맨 뒤.
            key = func.coalesce(p.expires_at, _POS_INF)
            order = (key.asc(), p.job_posting_id.asc())
            cmp = tuple_(key, p.job_posting_id).__gt__
        else:
            # 최신 게시순. 게시 중 공고만 볼 때는 published_at이 항상 있으므로 컬럼 그대로 써서
            # ix_job_postings_3 (status, published_at DESC)를 탈 수 있게 한다.
            key = p.published_at if not f.include_closed else func.coalesce(p.published_at, _NEG_INF)
            order = (key.desc(), p.job_posting_id.desc())
            cmp = tuple_(key, p.job_posting_id).__lt__

        stmt = self._posting_select(now).where(visible).order_by(*order).limit(limit)
        if after is not None:
            # anchor는 같은 조건에서 보이는 공고여야 한다 (사라졌거나 조건이 바뀌면 cursor 무효).
            anchor = self._db.execute(
                select(key.label("k")).where(p.job_posting_id == after, visible)
            ).one_or_none()
            if anchor is None:
                return None
            stmt = stmt.where(cmp(tuple_(literal(anchor.k, DateTime(timezone=True)), literal(after, Uuid))))
        return [self._row(r) for r in self._db.execute(stmt)]

    def get_posting(self, job_posting_id: UUID, now: datetime) -> PostingRow | None:
        p = job_postings.c
        row = self._db.execute(
            self._posting_select(now, detail=True)
            .where(p.job_posting_id == job_posting_id, p.status.in_(VISIBLE_STATUSES))
        ).one_or_none()
        return None if row is None else self._row(row, detail=True)

    def posting_skills(self, job_posting_id: UUID, job_role_id: UUID | None) -> list[PostingSkillRow]:
        ps, s, rs = job_posting_skills.c, skills.c, job_role_skills.c
        level = func.coalesce(ps.required_level, rs.required_level)
        stmt = (
            select(s.skill_id, s.code, s.name, level.label("level"), ps.is_required)
            .select_from(job_posting_skills)
            .join(skills, s.skill_id == ps.skill_id)
            .outerjoin(job_role_skills, and_(rs.skill_id == ps.skill_id, rs.job_role_id == job_role_id))
            .where(ps.job_posting_id == job_posting_id)
            .order_by(ps.is_required.desc(), level.desc().nulls_last(), s.name, s.skill_id)
        )
        return [
            PostingSkillRow(r.skill_id, r.code, r.name, None if r.level is None else int(r.level), r.is_required)
            for r in self._db.execute(stmt)
        ]

    def is_bookmarked(self, user_id: UUID, job_posting_id: UUID) -> bool:
        b = user_job_bookmarks.c
        return bool(self._db.execute(
            select(exists().where(b.user_id == user_id, b.job_posting_id == job_posting_id))
        ).scalar())
