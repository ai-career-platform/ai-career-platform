"""T126/T127 기업 공고 DB 접근. 표: database/migrations/0009_company_postings.sql (T125 설계, PR #349).

- 서비스(app/services/company_postings.py)의 저장소 계약(PostingRepository·PublicPostingSink·OrgDirectory) SQL 구현.
  세 객체는 요청의 Session 하나를 함께 쓴다 → 상태 변경·감사 이벤트·공개 행(job_postings) 변경이 한 트랜잭션.
- `transaction()` 은 재진입 가능하다. 가장 바깥 블록이 끝날 때만 commit, 예외면 rollback(공개 행만 남는 일 없음).
  커밋 시점에 0009 의 지연 제약 트리거가 "게시 상태가 아닌데 공개 행이 published" 인 경우를 한 번 더 거부한다.
- 동시성: 전이 대상 공고 행은 `SELECT … FOR UPDATE`, 게시(승인) 때 조직 행은 `FOR NO KEY UPDATE`
  (같은 조직의 공개 회사 행 생성을 직렬화, 소속 추가의 FK 검사는 막지 않음). 만료 처리는 `SKIP LOCKED`.
- 공개 표 쓰기는 source = company_direct 행에만 한다(수집 공고 jobkorea_live 등의 행·회사는 절대 건드리지 않음).
  company_direct data_sources 행이 없으면 승인은 503 으로 실패하고 아무것도 공개되지 않는다(롤백).
- 값은 모두 바인딩 변수. 로그를 쓰지 않는다. DDL 없음(T115 G6).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.services.company_postings import CompanyPosting, OrgInfo

COMPANY_DIRECT = "company_direct"
_COLUMNS = ("posting_id, organization_id, status, title, description, employment_type, location_text, apply_url, "
            "expires_at, version, created_by_user_id, updated_at, reason_code, reason_note, revision_of, "
            "public_posting_id, published_at")
_SELECT = f"SELECT {_COLUMNS} FROM career.organization_job_postings"
_EXPIRE_BATCH = 200


def _posting(r) -> CompanyPosting:
    return CompanyPosting(
        posting_id=r.posting_id, organization_id=r.organization_id, status=r.status, title=r.title,
        description=r.description, employment_type=r.employment_type, location_text=r.location_text,
        apply_url=r.apply_url, expires_at=r.expires_at, version=r.version, created_by=r.created_by_user_id,
        updated_at=r.updated_at, reason_code=r.reason_code, reason_note=r.reason_note, revision_of=r.revision_of,
        public_posting_id=r.public_posting_id, published_at=r.published_at)


def _params(p: CompanyPosting) -> dict:
    return {"id": p.posting_id, "org": p.organization_id, "status": p.status, "title": p.title,
            "description": p.description, "employment_type": p.employment_type, "location_text": p.location_text,
            "apply_url": p.apply_url, "expires_at": p.expires_at, "version": p.version, "created_by": p.created_by,
            "updated_at": p.updated_at, "reason_code": p.reason_code, "reason_note": p.reason_note,
            "revision_of": p.revision_of, "public_id": p.public_posting_id, "published_at": p.published_at}


class SqlPostingRepository:
    def __init__(self, session: Session) -> None:
        self.db = session
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._depth += 1
        try:
            yield
            if self._depth == 1:
                self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "23505":     # 동시 요청이 같은 유일 조건을 먼저 차지
                raise AppError(ErrorCode.CONFLICT, log_detail="unique constraint (concurrent change)") from None
            raise
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._depth -= 1

    def get(self, posting_id: UUID, *, lock: bool = False) -> CompanyPosting | None:
        row = self.db.execute(text(_SELECT + " WHERE posting_id = :id" + (" FOR UPDATE" if lock else "")),
                              {"id": posting_id}).first()
        return _posting(row) if row else None

    def add(self, posting: CompanyPosting) -> None:
        self.db.execute(text(
            "INSERT INTO career.organization_job_postings (posting_id, organization_id, status, title, description, "
            "employment_type, location_text, apply_url, expires_at, version, created_by_user_id, reason_code, "
            "reason_note, revision_of, public_posting_id, published_at, created_at, updated_at) VALUES (:id, :org, "
            ":status, :title, :description, :employment_type, :location_text, :apply_url, :expires_at, :version, "
            ":created_by, :reason_code, :reason_note, :revision_of, :public_id, :published_at, :updated_at, "
            ":updated_at)"), _params(posting))

    def save(self, posting: CompanyPosting) -> None:
        # 호출 전에 같은 트랜잭션에서 FOR UPDATE 로 읽었다(버전 비교는 서비스). organization_id·revision_of 는 바꾸지 않는다.
        updated = self.db.execute(text(
            "UPDATE career.organization_job_postings SET status = :status, title = :title, description = :description, "
            "employment_type = :employment_type, location_text = :location_text, apply_url = :apply_url, "
            "expires_at = :expires_at, version = :version, reason_code = :reason_code, reason_note = :reason_note, "
            "public_posting_id = :public_id, published_at = :published_at, updated_at = :updated_at "
            "WHERE posting_id = :id AND organization_id = :org"), _params(posting)).rowcount
        if updated != 1:
            raise AppError(ErrorCode.CONFLICT, log_detail="posting row vanished")

    def list_for_org(self, organization_id: UUID) -> list[CompanyPosting]:
        rows = self.db.execute(text(_SELECT + " WHERE organization_id = :org ORDER BY updated_at DESC, posting_id"),
                               {"org": organization_id}).all()
        return [_posting(r) for r in rows]

    def pending_review(self) -> list[CompanyPosting]:
        rows = self.db.execute(text(_SELECT + " WHERE status = 'pending_review' ORDER BY updated_at, posting_id")).all()
        return [_posting(r) for r in rows]

    def published_due(self, now: datetime) -> list[CompanyPosting]:
        rows = self.db.execute(text(
            _SELECT + " WHERE status = 'published' AND expires_at <= :now ORDER BY expires_at LIMIT :n "
            "FOR UPDATE SKIP LOCKED"), {"now": now, "n": _EXPIRE_BATCH}).all()
        return [_posting(r) for r in rows]

    def has_open_revision(self, original_id: UUID) -> bool:
        return self.db.execute(text(
            "SELECT EXISTS (SELECT 1 FROM career.organization_job_postings WHERE revision_of = :id "
            "AND status IN ('draft', 'pending_review', 'rejected'))"), {"id": original_id}).scalar_one()

    def record(self, event: dict) -> None:
        self.db.execute(text(
            "INSERT INTO career.organization_job_posting_events (posting_id, organization_id, action_code, "
            "actor_user_id, detail, occurred_at) VALUES (:posting_id, :organization_id, :action_code, "
            ":actor_user_id, :detail, :occurred_at)"), {**event, "detail": (event.get("detail") or "")[:80]})


class SqlPublicPostings:
    """career.job_postings 의 company_direct 행만 만든다·바꾼다·닫는다. 공고 저장소와 같은 Session(같은 트랜잭션)."""

    def __init__(self, session: Session) -> None:
        self.db = session

    def _source_id(self) -> UUID:
        source_id = self.db.execute(text("SELECT source_id FROM career.data_sources WHERE code = :c AND is_active"),
                                    {"c": COMPANY_DIRECT}).scalar()
        if source_id is None:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="data source company_direct not seeded")
        return source_id

    def _company_id(self, organization_id: UUID, name: str, source_id: UUID, now: datetime) -> UUID:
        # 호출자(승인)가 조직 행을 잠근 상태 → 같은 조직의 회사 행이 두 개 생기지 않는다.
        company_id = self.db.execute(text(
            "SELECT company_id FROM career.organization_public_companies WHERE organization_id = :o"),
            {"o": organization_id}).scalar()
        if company_id is None:
            company_id = self.db.execute(text(
                "INSERT INTO career.companies (name, source_id, created_at, updated_at) "
                "VALUES (:name, :s, :now, :now) RETURNING company_id"),
                {"name": name, "s": source_id, "now": now}).scalar_one()
            self.db.execute(text("INSERT INTO career.organization_public_companies (organization_id, company_id, "
                                 "created_at) VALUES (:o, :c, :now)"), {"o": organization_id, "c": company_id, "now": now})
        else:
            self.db.execute(text("UPDATE career.companies SET name = :name, updated_at = :now "
                                 "WHERE company_id = :c AND source_id = :s AND name <> :name"),
                            {"name": name, "now": now, "c": company_id, "s": source_id})
        return company_id

    def upsert(self, public_id: UUID | None, posting: CompanyPosting, organization_name: str,
               now: datetime) -> UUID:
        source_id = self._source_id()
        company_id = self._company_id(posting.organization_id, organization_name, source_id, now)
        # D-3(PM 결정 전): 지원 링크(apply_url)는 공개 행 source_url 로 복사하지 않는다(메모리 구현과 같음).
        params = {"company": company_id, "s": source_id, "title": posting.title, "description": posting.description,
                  "employment_type": posting.employment_type, "location_text": posting.location_text,
                  "published_at": posting.published_at or now, "expires_at": posting.expires_at, "now": now,
                  "id": public_id}
        if public_id is None:
            return self.db.execute(text(
                "INSERT INTO career.job_postings (company_id, source_id, title, description, employment_type, "
                "location_text, status, published_at, expires_at, created_at, updated_at) VALUES (:company, :s, "
                ":title, :description, :employment_type, :location_text, 'published', :published_at, :expires_at, "
                ":now, :now) RETURNING job_posting_id"), params).scalar_one()
        updated = self.db.execute(text(
            "UPDATE career.job_postings SET company_id = :company, title = :title, description = :description, "
            "employment_type = :employment_type, location_text = :location_text, status = 'published', "
            "published_at = :published_at, expires_at = :expires_at, updated_at = :now "
            "WHERE job_posting_id = :id AND source_id = :s"), params).rowcount
        if updated != 1:
            raise AppError(ErrorCode.CONFLICT, log_detail="public posting row missing or not company_direct")
        return public_id

    def close(self, public_id: UUID | None, now: datetime | None = None) -> None:
        if public_id is None:
            return
        self.db.execute(text(
            "UPDATE career.job_postings SET status = 'closed', updated_at = coalesce(:now, now()) "
            "WHERE job_posting_id = :id AND status <> 'closed' AND source_id = "
            "(SELECT source_id FROM career.data_sources WHERE code = :c)"),
            {"id": public_id, "now": now, "c": COMPANY_DIRECT})


class SqlOrgDirectory:
    """T122 표(0008)를 직접 읽는다. 쓰기는 하지 않는다(조직·소속 변경은 T123 기업 계정 API)."""

    def __init__(self, session: Session) -> None:
        self.db = session

    def organization(self, organization_id: UUID, *, lock: bool = False) -> OrgInfo | None:
        row = self.db.execute(text(
            "SELECT organization_id, name, status FROM career.organizations WHERE organization_id = :o"
            + (" FOR NO KEY UPDATE" if lock else "")), {"o": organization_id}).first()
        return OrgInfo(row.organization_id, row.name, row.status) if row else None

    def role_of(self, organization_id: UUID, user_id: UUID) -> str | None:
        return self.db.execute(text(
            "SELECT role FROM career.organization_members WHERE organization_id = :o AND user_id = :u"),
            {"o": organization_id, "u": user_id}).scalar()
