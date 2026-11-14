"""T81 운영 콘텐츠 검수(검수 큐·상세·담당·해제·승인·반려·이력) 서비스.

계약: docs/admin/MODERATION_IMPLEMENTATION_CONTRACT.md(§3 전이 규칙), 상태 모델 docs/admin/MODERATION_STATE_DIAGRAM.md,
API 제안 docs/admin/t81_openapi_proposal.yaml. 표: database/migrations/0010_moderation_cases.sql.

- 전이 하나 = 트랜잭션 하나. 순서(계약 §3): 대상 행 잠금(콘텐츠 효과가 있을 때) → 검수 건 `FOR UPDATE` → 상태·version·
  가드 확인 → 갱신(version+1) → 이력 1행 → 감사 1행 → 콘텐츠 효과 → Commit. 어느 단계든 실패하면 전부 롤백한다.
- **승인·반려와 공개 상태는 갈라지지 않는다.** 콘텐츠 효과가 필요한 결정은 그 대상 유형의 TargetEffect 가 같은
  트랜잭션 안에서 수행한다. company_posting(T125 기업 공고)은 기업 공고 관리자 결정과 **같은 전이 함수**(T125
  CompanyPostingTransitions.decide)를 부른다 — 별도 게시 경로가 없다. 효과 구현이 없는 유형의 결정은
  503 DEPENDENCY_UNAVAILABLE 로 거절하고 아무것도 바꾸지 않는다(검수 결과만 승인되고 공개는 그대로인 상태를 만들지 않음).
- 가드는 서버가 잠근 DB 값으로 판단한다: 자기 콘텐츠(소유자·제출자) 403, 담당자 아님 403, 재검토 단계 최초 결정자 403,
  결정·종료 건 409 APPROVAL_CLOSED, 상태·version 불일치 409 CONFLICT.
- 응답·감사·이력·로그에 관리자 메모(reviewer_note)·신고자 정보·콘텐츠 원문을 넣지 않는다.
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError, ErrorCode

TARGET_COLUMNS: dict[str, str] = {           # target_type → 대상별 FK 칸 (0010 CHECK 와 같아야 함)
    "job_posting": "job_posting_id", "company": "company_id", "shared_document": "document_id",
    "document_analysis": "analysis_id", "retrieval_run": "retrieval_run_id", "agent_run": "agent_run_id",
    "match_evaluation": "match_id", "recommendation_run": "recommendation_run_id",
    "company_posting": "company_posting_id",
}
TARGET_TYPES = tuple(TARGET_COLUMNS)
TRIGGERS = ("PRE_PUBLISH", "REPORT", "EXPIRY", "SOURCE_CHANGE")
STATUSES = ("PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "APPEALED", "CLOSED")
OPEN_STATUSES = frozenset({"PENDING", "IN_REVIEW", "APPEALED"})
FINISHED_STATUSES = frozenset({"APPROVED", "REJECTED", "CLOSED"})
REASON_CODES = ("RIGHTS_UNCLEAR", "INACCURATE", "PERSONAL_DATA", "HARMFUL", "DISCRIMINATORY", "DUPLICATE", "EXPIRED",
                "MALWARE", "OTHER")
NOTE_MAX = 500
DUE_AFTER = {1: timedelta(hours=24), 2: timedelta(hours=48), 3: timedelta(hours=72)}   # PM 결정 §9-7 달력 시간
AUDIT_ACTION, AUDIT_RESOURCE = "admin.content.review", "moderation_case"
# 승인 전 효과가 '공개'인 유형(계약 §1). 이 유형의 게시 전 승인은 효과 구현 없이는 할 수 없다.
PUBLISH_ON_APPROVE = frozenset({"job_posting", "company", "shared_document", "company_posting"})
# 원문 대신 보여 줄 유형 이름(공용 자료 파일 이름·AI 결과는 개인정보가 있을 수 있어 요약에 쓰지 않는다)
TYPE_LABELS = {
    "job_posting": "채용공고", "company": "기업", "shared_document": "공용 자료", "document_analysis": "AI 문서 분석",
    "retrieval_run": "AI 질의응답", "agent_run": "AI 작업", "match_evaluation": "AI 적합도",
    "recommendation_run": "AI 추천", "company_posting": "기업 직접 등록 공고",
}
# 검수 사유 코드 → T125 반려 사유 코드(PROPOSED 매핑, 정책 결정 필요). 없는 코드는 기업 공고 반려에 쓸 수 없다(422).
COMPANY_POSTING_REJECT_REASONS = {
    "PERSONAL_DATA": "personal_contact_info", "DISCRIMINATORY": "discriminatory_requirement",
    "DUPLICATE": "duplicate_posting", "INACCURATE": "misleading_terms", "OTHER": "other",
}


@dataclass(frozen=True)
class ModerationCase:
    case_id: UUID
    target_type: str
    target_id: UUID
    trigger: str
    status: str
    priority: int
    due_at: datetime
    created_at: datetime
    updated_at: datetime
    version: int = 1
    content_owner_id: UUID | None = None
    submitted_by: UUID | None = None
    assignee_id: UUID | None = None
    first_decider_id: UUID | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    reason_code: str | None = None
    reviewer_note: str | None = None      # 관리자 전용 — 응답·감사·이력에 넣지 않는다
    appeal_count: int = 0
    flags: tuple[str, ...] = ()
    report_count: int = 0
    close_reason: str | None = None
    target_live: bool = True              # 대상별 FK 칸이 아직 채워져 있는가(삭제되면 False)
    target_title: str | None = None       # 공개 가능한 제목(공고 제목·기업 이름)

    def overdue(self, now: datetime) -> bool:
        return self.status in OPEN_STATUSES and self.due_at < now

    def target_summary(self) -> str | None:
        if not self.target_live:
            return None
        return (self.target_title or TYPE_LABELS[self.target_type])[:200]


@dataclass(frozen=True)
class CaseEvent:
    event_id: UUID
    case_id: UUID
    event: str
    from_status: str | None
    to_status: str
    actor_user_id: UUID | None
    reason_code: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class CaseDetail:
    case: ModerationCase
    events: list[CaseEvent]


@dataclass(frozen=True)
class CasePage:
    items: list[ModerationCase]
    next_cursor: str | None


@dataclass(frozen=True)
class QueueFilter:
    status: str | None = None
    target_type: str | None = None
    priority: int | None = None
    overdue: bool | None = None

    def params(self) -> dict:
        return {"status": self.status, "target_type": self.target_type, "priority": self.priority,
                "overdue": self.overdue}


class ModerationRepository(Protocol):
    """한 요청(세션) 범위의 저장소. 쓰기 메서드는 커밋하지 않는다 — 서비스가 commit/rollback 한다."""

    def list_cases(self, flt: QueueFilter, after: tuple[int, datetime, UUID] | None, limit: int,
                   now: datetime) -> list[ModerationCase]: ...
    def get_case(self, case_id: UUID) -> ModerationCase | None: ...
    def lock_case(self, case_id: UUID) -> ModerationCase | None: ...
    def events(self, case_id: UUID) -> list[CaseEvent]: ...
    def save_case(self, case: ModerationCase, expected_version: int, now: datetime) -> bool: ...
    def add_event(self, case_id: UUID, event: str, from_status: str | None, to_status: str,
                  actor: UUID | None, reason_code: str | None, now: datetime) -> None: ...
    def audit(self, actor: UUID, case_id: UUID, request_id: str | None, now: datetime) -> None: ...
    def insert_case(self, case: ModerationCase) -> UUID | None: ...
    def find_open(self, target_type: str, target_id: UUID, trigger: str) -> ModerationCase | None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class TargetEffect(Protocol):
    """검수 결정의 콘텐츠 효과. 호출자(검수 서비스) 트랜잭션 안에서 실행하고 **커밋하지 않는다**."""

    def lock(self, target_id: UUID) -> None:
        """대상 행 `SELECT … FOR UPDATE`(검수 건보다 먼저, 계약 §2.1 잠금 순서)."""

    def apply(self, *, actor_id: UUID, roles: frozenset[str], target_id: UUID, decision: str,
              reason_code: str | None, note: str | None) -> None:
        """승인·반려의 콘텐츠 효과. 실패하면 AppError — 검수 전이도 함께 롤백된다."""


class CompanyPostingTransitions(Protocol):
    """T125 기업 공고 SQL 서비스가 제공해야 하는 전이(같은 DB 세션, 커밋하지 않음).

    `decide` 는 `/admin/company-postings/{id}/decision` 이 쓰는 것과 **같은 함수**여야 한다
    (CompanyPostingService.decide 와 같은 인자: decision 'approve'|'reject', T125 사유 코드, 메모, 공고 version).
    """

    def lock_posting(self, posting_id: UUID) -> int | None:
        """organization_job_postings 행을 FOR UPDATE 로 잠그고 현재 version 을 돌려준다(없으면 None)."""

    def decide(self, user_id: UUID, roles: frozenset[str], posting_id: UUID, decision: str,
               reason_code: str | None, note: str | None, version: int) -> object: ...


class CompanyPostingEffect:
    """company_posting 검수 건의 승인·반려 = T125 공고 결정(승인 → 게시·공개 행 생성, 반려 → rejected)."""

    def __init__(self, transitions: CompanyPostingTransitions) -> None:
        self._t = transitions
        self._versions: dict[UUID, int] = {}

    def lock(self, target_id: UUID) -> None:
        version = self._t.lock_posting(target_id)
        if version is None:
            raise AppError(ErrorCode.CONFLICT, log_detail="company posting target missing")
        self._versions[target_id] = version

    def apply(self, *, actor_id, roles, target_id, decision, reason_code, note) -> None:
        mapped = None
        if decision == "REJECT":
            mapped = COMPANY_POSTING_REJECT_REASONS.get(reason_code or "")
            if mapped is None:
                raise AppError(ErrorCode.VALIDATION_FAILED,
                               log_detail=f"reason {reason_code} has no company posting mapping")
        self._t.decide(actor_id, roles, target_id, decision.lower(), mapped,
                       note if decision == "REJECT" else None, self._versions[target_id])


def content_effect(target_type: str, trigger: str, decision: str) -> str:
    """결정에 필요한 콘텐츠 효과: 'none'(효과 없음) | 'target'(유형별 TargetEffect 필요).

    - 게시 전(PRE_PUBLISH) 승인 = 공개(공고·기업·공용 자료·기업 공고) → 효과 필요. AI 결과는 효과 없음.
    - 게시 전 반려 = 비공개 유지 → 효과 없음. 단 기업 공고는 T125 상태도 rejected 로 바꿔야 하므로 효과 필요.
    - 게시 후(신고·만료·출처 변경) 승인 = 게시 유지 → 효과 없음. 게시 후 반려 = 공개 철회·숨김 → 효과 필요.
    """
    if trigger == "PRE_PUBLISH":
        if decision == "APPROVE":
            return "target" if target_type in PUBLISH_ON_APPROVE else "none"
        return "target" if target_type == "company_posting" else "none"
    return "none" if decision == "APPROVE" else "target"


class ModerationService:
    def __init__(self, repo: ModerationRepository, cursor, effects: Mapping[str, TargetEffect] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.repo, self.cursor, self.effects, self.clock = repo, cursor, dict(effects or {}), clock

    # ------------------------------------------------------------ 공통
    def _run(self, fn):
        try:
            result = fn()
            self.repo.commit()
            return result
        except AppError:
            self.repo.rollback()
            raise
        except SQLAlchemyError as exc:
            self.repo.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE,
                           log_detail=f"moderation database error: {type(exc).__name__}") from None
        except BaseException:
            self.repo.rollback()
            raise

    def _detail(self, case_id: UUID) -> CaseDetail:
        case = self.repo.get_case(case_id)
        if case is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="moderation case missing")
        return CaseDetail(case, self.repo.events(case_id))

    def _locked(self, case_id: UUID) -> ModerationCase:
        case = self.repo.lock_case(case_id)
        if case is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="moderation case missing")
        return case

    @staticmethod
    def _check_version(case: ModerationCase, version: int) -> None:
        if case.version != version:
            raise AppError(ErrorCode.CONFLICT, log_detail="moderation case version mismatch")

    @staticmethod
    def _not_self(case: ModerationCase, actor: UUID) -> None:
        if actor in {case.content_owner_id, case.submitted_by}:
            raise AppError(ErrorCode.FORBIDDEN, log_detail="SELF_REVIEW")

    def _save(self, old: ModerationCase, new: ModerationCase, event: str, actor: UUID | None,
              reason_code: str | None, request_id: str | None, now: datetime) -> None:
        if not self.repo.save_case(new, old.version, now):
            raise AppError(ErrorCode.CONFLICT, log_detail="moderation case changed concurrently")
        self.repo.add_event(old.case_id, event, old.status, new.status, actor, reason_code, now)
        if actor is not None:
            self.repo.audit(actor, old.case_id, request_id, now)

    # ------------------------------------------------------------ 조회
    def list(self, flt: QueueFilter, limit: int, cursor: str | None) -> CasePage:
        params = flt.params()
        after = None
        if cursor:
            last_id, sort_key = self.cursor.decode(cursor, "moderation-cases", params)
            try:
                priority, due = (sort_key or "").split("|", 1)
                after = (int(priority), datetime.fromisoformat(due), last_id)
            except ValueError:
                raise AppError(ErrorCode.INVALID_CURSOR, log_detail="moderation cursor sort key") from None
        rows = self._run(lambda: self.repo.list_cases(flt, after, limit + 1, self.clock()))
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = self.cursor.encode("moderation-cases", params, last.case_id,
                                             f"{last.priority}|{last.due_at.isoformat()}")
        return CasePage(rows, next_cursor)

    def detail(self, actor: UUID, case_id: UUID, request_id: str | None = None) -> CaseDetail:
        """상세 + 이력. 열람도 감사에 남긴다(계약 §6) — 감사 실패면 상세도 503."""
        def run():
            found = self._detail(case_id)
            self.repo.audit(actor, case_id, request_id, self.clock())
            return found
        return self._run(run)

    # ------------------------------------------------------------ 전이
    def assign(self, actor: UUID, case_id: UUID, version: int, request_id: str | None = None) -> CaseDetail:
        """T02(PENDING → IN_REVIEW)·T09(APPEALED → IN_REVIEW, 최초 결정자 불가). 요청한 관리자 본인에게 배정."""
        def run():
            now = self.clock()
            case = self._locked(case_id)
            if case.status in FINISHED_STATUSES:
                raise AppError(ErrorCode.APPROVAL_CLOSED, log_detail=f"assign on {case.status}")
            if case.status == "IN_REVIEW":
                raise AppError(ErrorCode.CONFLICT, log_detail="already assigned")
            self._check_version(case, version)
            self._not_self(case, actor)
            if case.status == "APPEALED" and actor == case.first_decider_id:
                raise AppError(ErrorCode.FORBIDDEN, log_detail="FIRST_DECIDER_ON_APPEAL")
            new = replace(case, status="IN_REVIEW", assignee_id=actor, version=case.version + 1, updated_at=now)
            self._save(case, new, "ASSIGN", actor, None, request_id, now)
        self._run(run)
        return self._detail(case_id)

    def release(self, actor: UUID, case_id: UUID, version: int, request_id: str | None = None) -> CaseDetail:
        """T04(appeal_count 0 → PENDING)·T05(appeal_count 1 → APPEALED). 담당자 또는 관리자."""
        def run():
            now = self.clock()
            case = self._locked(case_id)
            if case.status in FINISHED_STATUSES:
                raise AppError(ErrorCode.APPROVAL_CLOSED, log_detail=f"release on {case.status}")
            if case.status != "IN_REVIEW":
                raise AppError(ErrorCode.CONFLICT, log_detail="release needs IN_REVIEW")
            self._check_version(case, version)
            to, event = ("APPEALED", "RELEASE_APPEAL") if case.appeal_count == 1 else ("PENDING", "RELEASE")
            new = replace(case, status=to, assignee_id=None, version=case.version + 1, updated_at=now)
            self._save(case, new, event, actor, None, request_id, now)
        self._run(run)
        return self._detail(case_id)

    @staticmethod
    def validate_decision(decision: str, reason_code: str | None, note: str | None) -> None:
        if decision not in {"APPROVE", "REJECT"}:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="decision")
        if note is not None and not 1 <= len(note) <= NOTE_MAX:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="note length")
        if decision == "APPROVE":
            if reason_code is not None or note is not None:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="approve takes no reason or note")
            return
        if reason_code not in REASON_CODES:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="reject needs a reason code")
        if reason_code == "OTHER" and not (note or "").strip():
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="OTHER needs a note")

    def decide(self, actor: UUID, roles: frozenset[str], case_id: UUID, version: int, decision: str,
               reason_code: str | None = None, note: str | None = None,
               request_id: str | None = None) -> CaseDetail:
        """T06 APPROVE·T07 REJECT — 담당자만. 콘텐츠 효과가 필요하면 같은 트랜잭션에서 대상 전이까지 한다."""
        self.validate_decision(decision, reason_code, note)

        def run():
            now = self.clock()
            peek = self.repo.get_case(case_id)      # target_type·trigger 는 불변(트리거) — 잠금 전에 읽어도 안전
            if peek is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="moderation case missing")
            effect = None
            if content_effect(peek.target_type, peek.trigger, decision) == "target":
                effect = self.effects.get(peek.target_type)
                if effect is None:   # 공개 상태를 바꿀 수 없으면 결정도 하지 않는다(아무것도 안 바뀜)
                    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE,
                                   log_detail=f"no content effect for {peek.target_type}/{peek.trigger}/{decision}")
                if not peek.target_live:
                    raise AppError(ErrorCode.CONFLICT, log_detail="target deleted")
                effect.lock(peek.target_id)          # ① 대상 행
            case = self._locked(case_id)             # ② 검수 건 행
            if case.status in FINISHED_STATUSES:
                raise AppError(ErrorCode.APPROVAL_CLOSED, log_detail=f"decide on {case.status}")
            if case.status != "IN_REVIEW":
                raise AppError(ErrorCode.CONFLICT, log_detail=f"decide on {case.status}")
            self._check_version(case, version)
            if case.assignee_id != actor:
                raise AppError(ErrorCode.FORBIDDEN, log_detail="NOT_ASSIGNEE")
            self._not_self(case, actor)
            if case.appeal_count == 1 and actor == case.first_decider_id:
                raise AppError(ErrorCode.FORBIDDEN, log_detail="FIRST_DECIDER_ON_APPEAL")
            approved = decision == "APPROVE"
            new = replace(case, status="APPROVED" if approved else "REJECTED", assignee_id=None,
                          first_decider_id=case.first_decider_id or (actor if case.appeal_count == 0 else None),
                          decided_by=actor, decided_at=now, reason_code=None if approved else reason_code,
                          reviewer_note=None if approved else note, version=case.version + 1, updated_at=now)
            self._save(case, new, decision, actor, new.reason_code, request_id, now)   # ③~⑥
            if effect is not None:                   # ⑦ 콘텐츠 효과(T125 전이) — 실패하면 위 갱신도 롤백
                effect.apply(actor_id=actor, roles=roles, target_id=case.target_id, decision=decision,
                             reason_code=reason_code, note=note)
        self._run(run)                               # ⑧ Commit
        return self._detail(case_id)

    # ------------------------------------------------------------ 접수(서버 내부, 공개 API 없음)
    def submit(self, target_type: str, target_id: UUID, trigger: str, *, priority: int | None = None,
               content_owner_id: UUID | None = None, submitted_by: UUID | None = None,
               flags: tuple[str, ...] = (), commit: bool = True) -> ModerationCase:
        """T01 SUBMIT. 같은 (대상, 계기)의 열린 건이 있으면 새로 만들지 않고 그 건을 돌려준다.

        commit=False 면 호출자(예: T125 검수 요청) 트랜잭션 안에서 실행하고 커밋하지 않는다.
        """
        if target_type not in TARGET_COLUMNS or trigger not in TRIGGERS:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="unknown target type or trigger")
        priority = priority or (2 if trigger == "REPORT" else 3)
        if priority not in DUE_AFTER:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="priority")
        now = self.clock()
        draft = ModerationCase(case_id=uuid.uuid4(), target_type=target_type, target_id=target_id, trigger=trigger,
                               status="PENDING", priority=priority, due_at=now + DUE_AFTER[priority], created_at=now,
                               updated_at=now, content_owner_id=content_owner_id, submitted_by=submitted_by,
                               flags=tuple(flags))

        def run():
            created = self.repo.insert_case(draft)
            if created is None:
                existing = self.repo.find_open(target_type, target_id, trigger)
                if existing is None:
                    raise AppError(ErrorCode.CONFLICT, log_detail="open case vanished during submit")
                return existing
            self.repo.add_event(created, "SUBMIT", None, "PENDING", submitted_by, None, now)
            return self.repo.get_case(created)
        if not commit:
            return run()
        return self._run(run)


# ---------------------------------------------------------------- 메모리 저장소(단위 시험용)
@dataclass
class MemoryModerationStore:
    cases: dict[UUID, ModerationCase] = field(default_factory=dict)
    events: list[CaseEvent] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class MemoryModerationRepository:
    """세션 하나를 흉내 낸다: 첫 쓰기 전 상태를 기억했다가 rollback 하면 되돌린다. 잠금은 commit/rollback 까지 유지."""

    def __init__(self, store: MemoryModerationStore) -> None:
        self.store = store
        self._snapshot = None
        self._locked = False

    def _begin(self) -> None:
        if not self._locked:
            self.store.lock.acquire()
            self._locked = True
            self._snapshot = (dict(self.store.cases), list(self.store.events), list(self.store.audit))

    def _end(self) -> None:
        self._snapshot = None
        if self._locked:
            self._locked = False
            self.store.lock.release()

    def list_cases(self, flt, after, limit, now):
        rows = [c for c in self.store.cases.values()
                if (flt.status is None or c.status == flt.status)
                and (flt.target_type is None or c.target_type == flt.target_type)
                and (flt.priority is None or c.priority == flt.priority)
                and (flt.overdue is None or c.overdue(now) == flt.overdue)]
        rows.sort(key=lambda c: (c.priority, c.due_at, str(c.case_id)))
        if after:
            rows = [c for c in rows if (c.priority, c.due_at, str(c.case_id)) > (after[0], after[1], str(after[2]))]
        return rows[:limit]

    def get_case(self, case_id):
        return self.store.cases.get(case_id)

    def lock_case(self, case_id):
        self._begin()
        return self.store.cases.get(case_id)

    def events(self, case_id):
        return sorted((e for e in self.store.events if e.case_id == case_id), key=lambda e: e.occurred_at)

    def save_case(self, case, expected_version, now):
        self._begin()
        current = self.store.cases.get(case.case_id)
        if current is None or current.version != expected_version:
            return False
        self.store.cases[case.case_id] = case
        return True

    def add_event(self, case_id, event, from_status, to_status, actor, reason_code, now):
        self._begin()
        self.store.events.append(CaseEvent(uuid.uuid4(), case_id, event, from_status, to_status, actor, reason_code,
                                           now))

    def audit(self, actor, case_id, request_id, now):
        self._begin()
        self.store.audit.append({"actor_user_id": actor, "action_code": AUDIT_ACTION, "resource_type": AUDIT_RESOURCE,
                                 "resource_id": case_id, "request_id": request_id, "occurred_at": now})

    def insert_case(self, case):
        self._begin()
        if self.find_open(case.target_type, case.target_id, case.trigger):
            return None
        self.store.cases[case.case_id] = case
        return case.case_id

    def find_open(self, target_type, target_id, trigger):
        return next((c for c in self.store.cases.values() if c.target_type == target_type and c.target_id == target_id
                     and c.trigger == trigger and c.status in OPEN_STATUSES), None)

    def commit(self):
        self._end()

    def rollback(self):
        if self._snapshot is not None:
            cases, events, audit = self._snapshot
            self.store.cases.clear()
            self.store.cases.update(cases)
            self.store.events[:] = events
            self.store.audit[:] = audit
        self._end()
