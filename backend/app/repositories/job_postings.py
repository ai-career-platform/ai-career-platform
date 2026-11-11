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
    Boolean, DateTime, Integer, String, Uuid, and_, case, column, exists, func, literal, literal_column, or_, select, table,
    tuple_,
)
from sqlalchemy.orm import Session

from app.services.job_search import POSTED_WITHIN, REGION_ALIASES

VISIBLE_STATUSES = ("published", "closed")


@dataclass(frozen=True)
class CompanyRow:
    company_id: UUID
    name: str
    sort_key: str  # 정렬에 쓴 값(lower(name)). cursor에 담아 다음 페이지 위치를 정한다.


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
    # T99 고급 검색(T98 제안, JOB_SEARCH_ADVANCED). 기본값이면 T18 동작과 같음.
    company_ids: tuple[UUID, ...] = ()
    job_role_ids: tuple[UUID, ...] = ()
    employment_types: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    posted_within: str | None = None
    q_matches_company: bool = False
    advanced: bool = False


# cursor가 가리키는 위치 = (마지막 항목의 정렬 키, 마지막 항목 id). 기준 행이 사라지거나 바뀌어도 이어 간다.
# 공고의 정렬 키가 None이면 "날짜 없음"(expires_at 정렬은 맨 뒤, 게시순은 맨 뒤)이다.
CompanyPosition = tuple[str, UUID]
PostingPosition = tuple[datetime | None, UUID]


class JobPostingRepository(Protocol):
    def list_companies(self, q: str | None, after: CompanyPosition | None, limit: int) -> list[CompanyRow]: ...

    def get_company(self, company_id: UUID, now: datetime) -> CompanyDetailRow | None: ...

    def list_postings(
        self, f: PostingFilter, after: PostingPosition | None, limit: int, now: datetime
    ) -> list[PostingRow]: ...

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

# 무한대는 SQL 상수로 씀(T99). 바인딩 값 + 캐스트(text→timestamptz 는 STABLE)로 보내면 식 인덱스
# (database/proposed/T99_job_search_indexes.sql 의 coalesce(expires_at, 'infinity'::timestamptz))와 맞지 않음.
_NEG_INF = literal_column("'-infinity'::timestamptz", DateTime(timezone=True))
_POS_INF = literal_column("'infinity'::timestamptz", DateTime(timezone=True))


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains(col, q: str):
    return col.ilike(f"%{escape_like(q)}%", escape="\\")


def region_token(col):
    """location_text 의 첫 단어 (T98 §4). 인덱스 제안(database/proposed/T99_job_search_indexes.sql)과 **같은 식**이어야 함."""
    return func.split_part(func.regexp_replace(func.btrim(col), literal_column(r"'\s+'"), literal_column("' '"),
                                               literal_column("'g'")), literal_column("' '"), literal_column("1"))


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
    def list_companies(self, q: str | None, after: CompanyPosition | None, limit: int) -> list[CompanyRow]:
        c = companies.c
        key = func.lower(c.name)  # ix_companies_1 (lower(name))
        stmt = select(c.company_id, c.name, key.label("sort_key")).order_by(key, c.company_id).limit(limit)
        if q:
            stmt = stmt.where(_contains(c.name, q))
        if after is not None:
            last_key, last_id = after
            stmt = stmt.where(tuple_(key, c.company_id) > tuple_(literal(last_key, String), literal(last_id, Uuid)))
        return [CompanyRow(r.company_id, r.name, r.sort_key) for r in self._db.execute(stmt)]

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
            conds.append(or_(_contains(p.title, f.q), _contains(companies.c.name, f.q)) if f.q_matches_company
                         else _contains(p.title, f.q))
        if f.company_id is not None:
            conds.append(p.company_id == f.company_id)
        if f.job_role_id is not None:
            conds.append(p.job_role_id == f.job_role_id)
        # 이하 T99 고급 검색. 값은 모두 바인딩 변수(문자열 연결 없음), 한 조건 안 여러 값은 OR, 조건끼리는 AND
        if f.company_ids:
            conds.append(p.company_id.in_(f.company_ids))
        if f.job_role_ids:
            conds.append(p.job_role_id.in_(f.job_role_ids))
        if f.employment_types:
            conds.append(p.employment_type.in_(f.employment_types))
        if f.regions:
            token = region_token(p.location_text)
            conds.append(or_(*[token.like(escape_like(alias) + "%", escape="\\")
                               for code in f.regions for alias in REGION_ALIASES[code]]))
        if f.posted_within:
            conds.append(p.published_at >= now - POSTED_WITHIN[f.posted_within])
        return and_(*conds)

    def list_postings(
        self, f: PostingFilter, after: PostingPosition | None, limit: int, now: datetime
    ) -> list[PostingRow]:
        p = job_postings.c
        if f.sort == "expires_at":
            # 마감 임박순. 마감일 없는 공고는 맨 뒤(+infinity로 취급).
            key, missing = func.coalesce(p.expires_at, _POS_INF), _POS_INF
            order = (key.asc(), p.job_posting_id.asc())
            cmp = tuple_(key, p.job_posting_id).__gt__
        else:
            # 최신 게시순. 게시 중 공고만 볼 때는 published_at이 항상 있으므로 컬럼 그대로 써서
            # ix_job_postings_3 (status, published_at DESC)를 탈 수 있게 한다.
            key = p.published_at if not f.include_closed else func.coalesce(p.published_at, _NEG_INF)
            missing = _NEG_INF
            order = (key.desc(), p.job_posting_id.desc())
            cmp = tuple_(key, p.job_posting_id).__lt__

        stmt = self._posting_select(now).where(self._visibility(f, now)).order_by(*order).limit(limit)
        if after is not None:
            # 기준 행을 다시 읽지 않는다. cursor의 (키, id)만으로 위치를 정하므로 기준 공고가 마감·삭제돼도 이어진다.
            # 무한대는 DB 쪽 리터럴로만 쓴다(파이썬 datetime으로는 표현할 수 없다).
            last_key, last_id = after
            anchor_key = missing if last_key is None else literal(last_key, DateTime(timezone=True))
            stmt = stmt.where(cmp(tuple_(anchor_key, literal(last_id, Uuid))))
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
