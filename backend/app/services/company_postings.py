"""T126 기업 공고 작성·검수 요청 서비스 (T125 상태 기계 — docs/enterprise/t125_posting_state_machine.json).

- 초안·검수 중·반려는 기업 쪽 저장소에만 있다. 공개 공고(job_postings)는 운영 승인(publish) 때만 생기거나 바뀐다
  (PublicPostingSink). 기업 역할에는 게시 전이가 없다(P-INV-1).
- 게시·반려·내림: 운영 관리자 + 그 조직 멤버 아님(P-INV-2). 반려·내림은 사유 코드 필수(P-INV-4).
- 모든 사람 행위 전이는 version 일치(P-INV-7) — 다르면 409 CONFLICT.
- 게시 중 공고 수정은 '수정본' 초안으로만. 수정본이 승인될 때만 공개 내용이 바뀐다.
- 원자성: 상태 변경·감사 이벤트·공개 행 변경은 모두 `repo.transaction()` 하나 안에서 일어난다. SQL 저장소에서는
  한 DB 트랜잭션(공고 행 `FOR UPDATE`)이고, 오류가 나면 전부 롤백된다(공개 행만 생기거나 상태만 바뀌는 일 없음).
- 저장소: MemoryPostingRepository(단위 시험), SqlPostingRepository(app/repositories/company_postings.py, migration 0009).
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.services.company_accounts import CompanyAccountService, CompanyRepository
from app.services.company_policy import Outcome, org_decision

TRANSITIONS: dict[tuple[str, str], str] = {          # (from, to) → action  (T125 JSON 과 같아야 함)
    ("draft", "pending_review"): "posting.submit_review",
    ("pending_review", "draft"): "posting.withdraw_review",
    ("pending_review", "published"): "posting.publish",
    ("pending_review", "rejected"): "posting.reject",
    ("rejected", "draft"): "posting.draft_edit",
    ("published", "closed"): "posting.close",
    ("published", "expired"): "system.expire",
    ("published", "taken_down"): "posting.takedown",
}
REJECT_REASONS = {"missing_required_info", "discriminatory_requirement", "personal_contact_info", "misleading_terms",
                  "not_a_job_posting", "duplicate_posting", "unverified_link", "other"}
TAKEDOWN_REASONS = {"legal_request", "fraud_suspected", "discriminatory_requirement", "organization_suspended", "other"}
MAX_PUBLISH = timedelta(days=60)
REQUIRED = ("title", "description", "employment_type", "location_text", "expires_at")
EMPLOYMENT_TYPES = {"full_time", "contract", "intern", "part_time"}
EDITABLE = ("title", "description", "employment_type", "location_text", "apply_url", "expires_at")
OPEN_REVISION = frozenset({"draft", "pending_review", "rejected"})


@dataclass(frozen=True)
class CompanyPosting:
    posting_id: uuid.UUID
    organization_id: uuid.UUID
    status: str
    title: str
    description: str | None = None
    employment_type: str | None = None
    location_text: str | None = None
    apply_url: str | None = None
    expires_at: datetime | None = None
    version: int = 1
    created_by: uuid.UUID | None = None
    updated_at: datetime | None = None
    reason_code: str | None = None
    reason_note: str | None = None
    revision_of: uuid.UUID | None = None
    public_posting_id: uuid.UUID | None = None
    published_at: datetime | None = None


@dataclass(frozen=True)
class OrgInfo:
    organization_id: uuid.UUID
    name: str
    status: str


# ------------------------------------------------------------------ 저장소 계약
class OrgDirectory(Protocol):
    """조직 상태·소속 역할 조회(T122 표). lock=True 면 같은 트랜잭션 동안 조직 행을 잠근다(게시 직렬화)."""

    def organization(self, organization_id: uuid.UUID, *, lock: bool = False) -> OrgInfo | None: ...

    def role_of(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> str | None: ...


class PostingRepository(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...

    def get(self, posting_id: uuid.UUID, *, lock: bool = False) -> CompanyPosting | None: ...

    def add(self, posting: CompanyPosting) -> None: ...

    def save(self, posting: CompanyPosting) -> None: ...

    def list_for_org(self, organization_id: uuid.UUID) -> list[CompanyPosting]: ...

    def pending_review(self) -> list[CompanyPosting]: ...

    def published_due(self, now: datetime) -> list[CompanyPosting]: ...

    def has_open_revision(self, original_id: uuid.UUID) -> bool: ...

    def record(self, event: dict) -> None: ...


class PublicPostingSink(Protocol):
    """공개 공고 표(job_postings). 반드시 PostingRepository 와 같은 트랜잭션 안에서만 부른다."""

    def upsert(self, public_id: uuid.UUID | None, posting: CompanyPosting, organization_name: str,
               now: datetime) -> uuid.UUID: ...

    def close(self, public_id: uuid.UUID | None, now: datetime | None = None) -> None: ...


# ------------------------------------------------------------------ 메모리 구현(단위 시험)
@dataclass
class MemoryPublicPostings:
    """공개 공고 표(job_postings) 대역. source=company_direct."""

    rows: dict[uuid.UUID, dict] = field(default_factory=dict)

    def upsert(self, public_id: uuid.UUID | None, posting: CompanyPosting, organization_name: str,
               now: datetime) -> uuid.UUID:
        public_id = public_id or uuid.uuid4()
        self.rows[public_id] = {"job_posting_id": public_id, "title": posting.title, "company": organization_name,
                                "description": posting.description, "employment_type": posting.employment_type,
                                "location_text": posting.location_text, "status": "published",
                                "published_at": posting.published_at or now, "expires_at": posting.expires_at,
                                "source": "company_direct"}
        return public_id

    def close(self, public_id: uuid.UUID | None, now: datetime | None = None) -> None:
        if public_id in self.rows:
            self.rows[public_id]["status"] = "closed"

    def published(self) -> list[dict]:
        return [r for r in self.rows.values() if r["status"] == "published"]


@dataclass
class MemoryPostingRepository:
    postings: dict[uuid.UUID, CompanyPosting] = field(default_factory=dict)
    audit: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.lock:
            yield

    def get(self, posting_id: uuid.UUID, *, lock: bool = False) -> CompanyPosting | None:
        return self.postings.get(posting_id)

    def add(self, posting: CompanyPosting) -> None:
        self.postings[posting.posting_id] = posting

    save = add

    def list_for_org(self, organization_id: uuid.UUID) -> list[CompanyPosting]:
        rows = [p for p in self.postings.values() if p.organization_id == organization_id]
        return sorted(rows, key=lambda p: p.updated_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def pending_review(self) -> list[CompanyPosting]:
        return sorted((p for p in self.postings.values() if p.status == "pending_review"), key=lambda p: p.updated_at)

    def published_due(self, now: datetime) -> list[CompanyPosting]:
        return [p for p in self.postings.values()
                if p.status == "published" and p.expires_at and p.expires_at <= now]

    def has_open_revision(self, original_id: uuid.UUID) -> bool:
        return any(p.revision_of == original_id and p.status in OPEN_REVISION for p in self.postings.values())

    def record(self, event: dict) -> None:
        self.audit.append(event)


@dataclass
class MemoryOrgDirectory:
    """T123 기업 저장소(CompanyRepository)를 그대로 읽는다(멤버 변경이 즉시 반영). 단위 시험용."""

    repo: CompanyRepository

    def organization(self, organization_id: uuid.UUID, *, lock: bool = False) -> OrgInfo | None:
        org = self.repo.get_organization(organization_id)
        return OrgInfo(org.organization_id, org.name, org.status) if org else None

    def role_of(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        return self.repo.role_of(organization_id, user_id)


_URL = re.compile(r"^https://[^\s/$.?#].[^\s]*$")


def _require_admin_role(roles: frozenset[str]) -> None:
    if "admin" not in roles:
        raise AppError(ErrorCode.FORBIDDEN, log_detail="admin only")


def _filled(value) -> bool:
    return bool(value.strip()) if isinstance(value, str) else value is not None


class CompanyPostingService:
    def __init__(self, orgs: OrgDirectory | CompanyAccountService, repo: PostingRepository, public: PublicPostingSink,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.orgs: OrgDirectory = MemoryOrgDirectory(orgs.repo) if isinstance(orgs, CompanyAccountService) else orgs
        self.repo, self.public, self.clock = repo, public, clock

    # ------------------------------------------------------------ 공통
    def _org_scope(self, action: str, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrgInfo | None:
        org = self.orgs.organization(organization_id)
        role = self.orgs.role_of(organization_id, user_id) if org else None
        outcome = org_decision(action, role, org.status if org else "closed")
        if outcome is Outcome.HIDDEN:
            raise AppError(ErrorCode.NOT_FOUND, log_detail=f"{action}: not a member")
        if outcome is Outcome.FORBIDDEN:
            raise AppError(ErrorCode.FORBIDDEN, log_detail=f"{action}: role {role} / org {org and org.status}")
        return org

    def _posting(self, organization_id: uuid.UUID, posting_id: uuid.UUID, *, lock: bool = False) -> CompanyPosting:
        posting = self.repo.get(posting_id, lock=lock)
        if posting is None or posting.organization_id != organization_id:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="posting missing or other organization")
        return posting

    def _admin(self, user_id: uuid.UUID, roles: frozenset[str], posting: CompanyPosting) -> None:
        if "admin" not in roles:
            raise AppError(ErrorCode.FORBIDDEN, log_detail="admin only")
        if self.orgs.role_of(posting.organization_id, user_id):
            raise AppError(ErrorCode.FORBIDDEN, log_detail="admin is a member of the posting organization")

    def _move(self, posting: CompanyPosting, to: str, version: int | None, *, save: bool = True,
              **changes) -> CompanyPosting:
        if (posting.status, to) not in TRANSITIONS:
            raise AppError(ErrorCode.CONFLICT, log_detail=f"transition {posting.status}->{to} not allowed")
        if version is not None and posting.version != version:
            raise AppError(ErrorCode.CONFLICT, log_detail="version mismatch")
        moved = replace(posting, status=to, version=posting.version + 1, updated_at=self.clock(), **changes)
        if save:
            self.repo.save(moved)
        return moved

    def _record(self, action: str, actor: uuid.UUID | None, posting: CompanyPosting, extra: str = "") -> None:
        self.repo.record({"action_code": action, "actor_user_id": actor, "posting_id": posting.posting_id,
                          "organization_id": posting.organization_id, "detail": extra,
                          "occurred_at": self.clock()})

    @staticmethod
    def _validate_fields(values: dict) -> None:
        if "title" in values and not _filled(values["title"]):
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="title is required")
        if "employment_type" in values and values["employment_type"] not in EMPLOYMENT_TYPES | {None}:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="employment_type")
        if values.get("apply_url") and not _URL.match(values["apply_url"]):
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="apply_url must be https")

    # ------------------------------------------------------------ 기업 쪽
    def list(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> list[CompanyPosting]:
        self.expire_due()
        with self.repo.transaction():
            self._org_scope("posting.view_internal", organization_id, user_id)
            return self.repo.list_for_org(organization_id)

    def get(self, user_id: uuid.UUID, organization_id: uuid.UUID, posting_id: uuid.UUID) -> CompanyPosting:
        self.expire_due()
        with self.repo.transaction():
            self._org_scope("posting.view_internal", organization_id, user_id)
            return self._posting(organization_id, posting_id)

    def create(self, user_id: uuid.UUID, organization_id: uuid.UUID, values: dict) -> CompanyPosting:
        self._validate_fields(values)
        with self.repo.transaction():
            self._org_scope("posting.draft_create", organization_id, user_id)
            posting = CompanyPosting(uuid.uuid4(), organization_id, "draft", created_by=user_id,
                                     updated_at=self.clock(), **{k: values.get(k) for k in EDITABLE})
            self.repo.add(posting)
            self._record("posting.draft_create", user_id, posting)
        return posting

    def edit(self, user_id: uuid.UUID, organization_id: uuid.UUID, posting_id: uuid.UUID, values: dict,
             version: int) -> CompanyPosting:
        self._validate_fields(values)
        with self.repo.transaction():
            self._org_scope("posting.draft_edit", organization_id, user_id)
            posting = self._posting(organization_id, posting_id, lock=True)
            if posting.version != version:
                raise AppError(ErrorCode.CONFLICT, log_detail="version mismatch")
            if posting.status == "rejected":                 # 반려 공고를 고치면 초안으로(T125)
                posting = self._move(posting, "draft", version, reason_code=None, reason_note=None)
            elif posting.status == "draft":
                posting = replace(posting, version=posting.version + 1)
            else:   # 검수 중·게시 중·종료 공고는 직접 수정 불가(게시 중이면 수정본)
                raise AppError(ErrorCode.CONFLICT, log_detail=f"cannot edit in {posting.status}")
            updated = replace(posting, updated_at=self.clock(), **{k: v for k, v in values.items() if k in EDITABLE})
            self.repo.save(updated)
            self._record("posting.draft_edit", user_id, updated)
        return updated

    def revise(self, user_id: uuid.UUID, organization_id: uuid.UUID, posting_id: uuid.UUID) -> CompanyPosting:
        with self.repo.transaction():
            self._org_scope("posting.draft_create", organization_id, user_id)
            original = self._posting(organization_id, posting_id, lock=True)
            if original.status != "published":
                raise AppError(ErrorCode.CONFLICT, log_detail="only published postings get revisions")
            if self.repo.has_open_revision(posting_id):
                raise AppError(ErrorCode.CONFLICT, log_detail="an open revision exists")
            draft = CompanyPosting(uuid.uuid4(), organization_id, "draft", created_by=user_id, updated_at=self.clock(),
                                   revision_of=posting_id, **{k: getattr(original, k) for k in EDITABLE})
            self.repo.add(draft)
            self._record("posting.revision_create", user_id, draft, str(posting_id))
        return draft

    def submit(self, user_id: uuid.UUID, organization_id: uuid.UUID, posting_id: uuid.UUID, version: int):
        with self.repo.transaction():
            org = self._org_scope("posting.submit_review", organization_id, user_id)
            if org is None or org.status != "active":
                raise AppError(ErrorCode.FORBIDDEN, log_detail="organization not active")
            posting = self._posting(organization_id, posting_id, lock=True)
            missing = [k for k in REQUIRED if not _filled(getattr(posting, k))]
            if missing:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"missing {missing}")
            moved = self._move(posting, "pending_review", version)
            self._record("posting.submit_review", user_id, moved)
        return moved

    def withdraw(self, user_id: uuid.UUID, organization_id: uuid.UUID, posting_id: uuid.UUID, version: int):
        with self.repo.transaction():
            self._org_scope("posting.withdraw_review", organization_id, user_id)
            moved = self._move(self._posting(organization_id, posting_id, lock=True), "draft", version)
            self._record("posting.withdraw_review", user_id, moved)
        return moved

    def close(self, user_id: uuid.UUID, roles: frozenset[str], organization_id: uuid.UUID, posting_id: uuid.UUID,
              version: int) -> CompanyPosting:
        with self.repo.transaction():
            if "admin" not in roles or self.orgs.role_of(organization_id, user_id):
                self._org_scope("posting.close", organization_id, user_id)
            moved = self._move(self._posting(organization_id, posting_id, lock=True), "closed", version)
            self.public.close(moved.public_posting_id, self.clock())
            self._record("posting.close", user_id, moved)
        return moved

    # ------------------------------------------------------------ 운영 관리자
    def queue(self, user_id: uuid.UUID, roles: frozenset[str]) -> list[CompanyPosting]:
        _require_admin_role(roles)
        with self.repo.transaction():
            return self.repo.pending_review()

    def decide(self, user_id: uuid.UUID, roles: frozenset[str], posting_id: uuid.UUID, decision: str,
               reason_code: str | None, note: str | None, version: int) -> CompanyPosting:
        now = self.clock()
        _require_admin_role(roles)       # T148 F-2: 존재 확인보다 먼저(비관리자에게 id 존재 여부를 알리지 않음)
        with self.repo.transaction():
            posting = self.repo.get(posting_id, lock=True)
            if posting is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="posting missing")
            self._admin(user_id, roles, posting)
            if decision == "reject":
                if reason_code not in REJECT_REASONS or (reason_code == "other" and not (note or "").strip()):
                    raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="reject needs a reason code")
                moved = self._move(posting, "rejected", version, reason_code=reason_code, reason_note=note)
                self._record("posting.reject", user_id, moved, reason_code)
                return moved
            # 승인: 상태 전이를 먼저 검사(중복 승인·버전 불일치는 공개 표를 건드리기 전에 409)
            if (posting.status, "published") not in TRANSITIONS or posting.version != version:
                raise AppError(ErrorCode.CONFLICT, log_detail="cannot approve: state or version changed")
            org = self.orgs.organization(posting.organization_id, lock=True)
            if org is None or org.status != "active":
                raise AppError(ErrorCode.CONFLICT, log_detail="organization not active")
            if not posting.expires_at or not now < posting.expires_at <= now + MAX_PUBLISH:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="expires_at must be within 60 days")
            original = None
            if posting.revision_of:
                original = self.repo.get(posting.revision_of, lock=True)
                if original is None or original.status != "published":   # 원본이 마감·내림·만료되면 다시 열지 않음
                    raise AppError(ErrorCode.CONFLICT, log_detail="original posting is no longer published")
            # 저장은 공개 행이 생긴 뒤 한 번만(DB CHECK: published 원본은 공개 행 필수). 모두 같은 트랜잭션.
            moved = self._move(posting, "published", version, save=False, published_at=now)
            if original is not None:
                merged = replace(original, version=original.version + 1, updated_at=now,
                                 **{k: getattr(moved, k) for k in EDITABLE})
                self.repo.save(merged)
                self.public.upsert(original.public_posting_id, merged, org.name, now)
                moved = replace(moved, status="closed", reason_note="merged into original")
                self.repo.save(moved)
            else:
                public_id = self.public.upsert(None, moved, org.name, now)
                moved = replace(moved, public_posting_id=public_id)
                self.repo.save(moved)
            self._record("posting.publish", user_id, moved)
        return moved

    def takedown(self, user_id: uuid.UUID, roles: frozenset[str], posting_id: uuid.UUID, reason_code: str,
                 note: str | None) -> CompanyPosting:
        _require_admin_role(roles)       # T148 F-2
        with self.repo.transaction():
            posting = self.repo.get(posting_id, lock=True)
            if posting is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="posting missing")
            self._admin(user_id, roles, posting)
            if reason_code not in TAKEDOWN_REASONS:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="takedown needs a reason code")
            moved = self._move(posting, "taken_down", None, reason_code=reason_code, reason_note=note)
            self.public.close(moved.public_posting_id, self.clock())
            self._record("posting.takedown", user_id, moved, reason_code)
        return moved

    def expire_due(self) -> int:
        now, count = self.clock(), 0
        with self.repo.transaction():
            for posting in self.repo.published_due(now):
                moved = self._move(posting, "expired", None)
                self.public.close(moved.public_posting_id, now)
                self._record("system.expire", None, moved)
                count += 1
        return count
