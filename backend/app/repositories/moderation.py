"""T81 운영 콘텐츠 검수 DB 접근. 표: database/migrations/0010_moderation_cases.sql.

- 쓰기 메서드는 커밋하지 않는다. 서비스(ModerationService)가 전이 하나를 한 트랜잭션으로 묶어 commit/rollback 한다.
- 검수 건 잠금은 `SELECT … FOR UPDATE`(lock_case). 저장은 `WHERE version = :expected` 로 한 번 더 막는다.
- 값은 바인딩 변수로만 전달한다. 대상별 FK 칸 이름은 서비스의 고정 사전(TARGET_COLUMNS)에서만 고른다.
- 이 모듈은 로그를 쓰지 않는다(메모·신고자·콘텐츠 원문이 로그에 남지 않음).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.services.moderation import AUDIT_ACTION, AUDIT_RESOURCE, TARGET_COLUMNS, CaseEvent, ModerationCase, QueueFilter

_COLUMNS = ("c.case_id, c.target_type, c.target_id, c.review_trigger, c.status, c.priority, c.content_owner_id, "
            "c.submitted_by, c.assignee_id, c.first_decider_id, c.decided_by, c.decided_at, c.reason_code, "
            "c.reviewer_note, c.appeal_count, c.flags, c.report_count, c.due_at, c.close_reason, c.version, "
            "c.created_at, c.updated_at, career.moderation_case_live_target(c) IS NOT NULL AS target_live")
# 공개 가능한 대상 제목만(공고 제목·기업 이름·기업 공고 제목). 공용 자료 파일 이름·AI 결과는 쓰지 않는다.
_TITLE = ("CASE c.target_type "
          "WHEN 'job_posting' THEN (SELECT jp.title FROM career.job_postings jp WHERE jp.job_posting_id = c.job_posting_id) "
          "WHEN 'company' THEN (SELECT co.name FROM career.companies co WHERE co.company_id = c.company_id) "
          "WHEN 'company_posting' THEN (SELECT op.title FROM career.organization_job_postings op "
          "WHERE op.posting_id = c.company_posting_id) END AS target_title")
_OPEN = "('PENDING', 'IN_REVIEW', 'APPEALED')"


def _case(r) -> ModerationCase:
    return ModerationCase(
        case_id=r.case_id, target_type=r.target_type, target_id=r.target_id, trigger=r.review_trigger,
        status=r.status, priority=r.priority, due_at=r.due_at, created_at=r.created_at, updated_at=r.updated_at,
        version=r.version, content_owner_id=r.content_owner_id, submitted_by=r.submitted_by,
        assignee_id=r.assignee_id, first_decider_id=r.first_decider_id, decided_by=r.decided_by,
        decided_at=r.decided_at, reason_code=r.reason_code, reviewer_note=r.reviewer_note,
        appeal_count=r.appeal_count, flags=tuple(r.flags or ()), report_count=r.report_count,
        close_reason=r.close_reason, target_live=r.target_live, target_title=getattr(r, "target_title", None))


class SqlModerationRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    # ------------------------------------------------------------ 조회
    def list_cases(self, flt: QueueFilter, after, limit: int, now: datetime) -> list[ModerationCase]:
        where, params = [], {"limit": limit, "now": now}
        if flt.status is not None:
            where.append("c.status = :status")
            params["status"] = flt.status
        if flt.target_type is not None:
            where.append("c.target_type = :target_type")
            params["target_type"] = flt.target_type
        if flt.priority is not None:
            where.append("c.priority = :priority")
            params["priority"] = flt.priority
        if flt.overdue is not None:
            overdue = f"(c.status IN {_OPEN} AND c.due_at < :now)"
            where.append(overdue if flt.overdue else f"NOT {overdue}")
        if after is not None:
            where.append("(c.priority, c.due_at, c.case_id) > (:a_priority, :a_due, :a_id)")
            params.update(a_priority=after[0], a_due=after[1], a_id=after[2])
        sql = (f"SELECT {_COLUMNS}, {_TITLE} FROM career.moderation_cases c "
               + (f"WHERE {' AND '.join(where)} " if where else "")
               + "ORDER BY c.priority, c.due_at, c.case_id LIMIT :limit")
        return [_case(r) for r in self.db.execute(text(sql), params)]

    def get_case(self, case_id: UUID) -> ModerationCase | None:
        row = self.db.execute(text(f"SELECT {_COLUMNS}, {_TITLE} FROM career.moderation_cases c WHERE c.case_id = :id"),
                              {"id": case_id}).first()
        return _case(row) if row else None

    def lock_case(self, case_id: UUID) -> ModerationCase | None:
        row = self.db.execute(text(f"SELECT {_COLUMNS} FROM career.moderation_cases c WHERE c.case_id = :id FOR UPDATE"),
                              {"id": case_id}).first()
        return _case(row) if row else None

    def events(self, case_id: UUID) -> list[CaseEvent]:
        rows = self.db.execute(text(
            "SELECT event_id, case_id, event, from_status, to_status, actor_user_id, reason_code, occurred_at "
            "FROM career.moderation_case_events WHERE case_id = :id ORDER BY occurred_at, event_id"), {"id": case_id})
        return [CaseEvent(r.event_id, r.case_id, r.event, r.from_status, r.to_status, r.actor_user_id, r.reason_code,
                          r.occurred_at) for r in rows]

    def find_open(self, target_type: str, target_id: UUID, trigger: str) -> ModerationCase | None:
        row = self.db.execute(text(
            f"SELECT {_COLUMNS}, {_TITLE} FROM career.moderation_cases c WHERE c.target_type = :t AND c.target_id = :id "
            f"AND c.review_trigger = :tr AND c.status IN {_OPEN}"), {"t": target_type, "id": target_id, "tr": trigger}
        ).first()
        return _case(row) if row else None

    # ------------------------------------------------------------ 쓰기(커밋 안 함)
    def save_case(self, case: ModerationCase, expected_version: int, now: datetime) -> bool:
        saved = self.db.execute(text(
            "UPDATE career.moderation_cases SET status = :status, assignee_id = :assignee, "
            "first_decider_id = :first, decided_by = :decided_by, decided_at = :decided_at, "
            "reason_code = :reason, reviewer_note = :note, version = :version, updated_at = :now "
            "WHERE case_id = :id AND version = :expected RETURNING case_id"),
            {"status": case.status, "assignee": case.assignee_id, "first": case.first_decider_id,
             "decided_by": case.decided_by, "decided_at": case.decided_at, "reason": case.reason_code,
             "note": case.reviewer_note, "version": case.version, "now": now, "id": case.case_id,
             "expected": expected_version}).first()
        return saved is not None

    def add_event(self, case_id, event, from_status, to_status, actor, reason_code, now) -> None:
        self.db.execute(text(
            "INSERT INTO career.moderation_case_events (case_id, from_status, to_status, event, actor_user_id, "
            "reason_code, occurred_at) VALUES (:case_id, :from_status, :to_status, :event, :actor, :reason, :now)"),
            {"case_id": case_id, "from_status": from_status, "to_status": to_status, "event": event, "actor": actor,
             "reason": reason_code, "now": now})

    def audit(self, actor: UUID, case_id: UUID, request_id: str | None, now: datetime) -> None:
        self.db.execute(text(
            "INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, request_id, "
            "occurred_at) VALUES (:actor, :action, :resource, :id, :request_id, :now)"),
            {"actor": actor, "action": AUDIT_ACTION, "resource": AUDIT_RESOURCE, "id": case_id,
             "request_id": request_id, "now": now})

    def insert_case(self, case: ModerationCase) -> UUID | None:
        column = TARGET_COLUMNS[case.target_type]      # 고정 사전 — 사용자 입력이 SQL 이름이 되지 않음
        try:
            with self.db.begin_nested():               # 없는 대상(FK) 오류가 호출자 트랜잭션을 망치지 않게
                return self.db.execute(text(
                    f"INSERT INTO career.moderation_cases (case_id, target_type, target_id, {column}, review_trigger, "
                    "priority, content_owner_id, submitted_by, flags, due_at, created_at, updated_at) "
                    "VALUES (:case_id, :target_type, :target_id, :target_id, :trigger, :priority, :owner, :submitted_by, "
                    "CAST(:flags AS text[]), :due_at, :now, :now) "
                    f"ON CONFLICT (target_type, target_id, review_trigger) WHERE status IN {_OPEN} DO NOTHING "
                    "RETURNING case_id"),
                    {"case_id": case.case_id, "target_type": case.target_type, "target_id": case.target_id,
                     "trigger": case.trigger, "priority": case.priority, "owner": case.content_owner_id,
                     "submitted_by": case.submitted_by, "flags": list(case.flags) or None, "due_at": case.due_at,
                     "now": case.created_at}).scalar()
        except IntegrityError:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="moderation target missing") from None

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
