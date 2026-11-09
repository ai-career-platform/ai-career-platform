"""T47 추천 피드백 DB 접근 (database/DATA_DICTIONARY.md D05~D07, F11, 스키마 `career`).

- 서비스는 `RecommendationFeedbackRepository` 프로토콜에만 의존한다. 테스트는 `tests/fakes.py`의 메모리 구현을 쓴다.
- T45(추천 실행 API)가 아직 머지되지 않아 `recommendation_runs`/`recommendation_items` 쓰기 코드는 없다.
  여기서는 소유권 확인에 필요한 SELECT만 하고, 이 프로토콜이 T45와 T47의 좁은 접점이다.
- 공유 ORM 모델을 새로 만들지 않고 쓰는 컬럼만 `table()`로 적는다 (T17·T18과 같은 방식).
  테이블은 T09 `0001_initial_schema.sql`에 이미 있으며 DDL을 추가하지 않는다.
- `recommendation_feedback`은 추가만 한다(D07). 공고별 최신 행이 현재 피드백이다.
- 쓰기는 서비스가 `commit()`을 호출해야 확정된다 (T15 `AuthRepository`와 같은 규칙).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid, and_, column, exists, func, insert, literal, select, table
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class FeedbackRecord:
    feedback_id: UUID
    user_id: UUID
    recommendation_run_id: UUID | None
    job_posting_id: UUID
    feedback: str  # liked | not_interested | cleared
    created_at: datetime


@dataclass(frozen=True)
class AuditRecord:
    """F11 `audit_events`의 T05 기본 컬럼만 쓴다. 이메일·입력값 등 개인정보는 넣지 않는다."""

    actor_user_id: UUID
    action_code: str
    resource_type: str
    resource_id: UUID
    request_id: str | None
    occurred_at: datetime


class RecommendationFeedbackRepository(Protocol):
    def lock_feedback(self, user_id: UUID, job_posting_id: UUID) -> None:
        """같은 사용자·공고의 동시 요청을 줄 세운다(트랜잭션 끝에 풀림). 중복 판정이 경합하지 않게 한다."""
        ...

    def is_recommended_to(self, user_id: UUID, job_posting_id: UUID, recommendation_run_id: UUID | None) -> bool:
        """공고가 이 사용자의 추천 실행(run_id를 주면 그 실행)에 들어 있었는가."""
        ...

    def latest_feedback(self, user_id: UUID, job_posting_ids: list[UUID]) -> dict[UUID, FeedbackRecord]:
        """공고별 이 사용자의 최신 피드백 행. 기록이 없는 공고는 결과에 없다."""
        ...

    def insert_feedback(self, record: FeedbackRecord) -> None: ...

    def record_audit(self, event: AuditRecord) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


_SCHEMA = "career"
recommendation_runs = table(
    "recommendation_runs", column("recommendation_run_id", Uuid), column("user_id", Uuid), schema=_SCHEMA,
)
recommendation_items = table(
    "recommendation_items", column("recommendation_run_id", Uuid), column("job_posting_id", Uuid), schema=_SCHEMA,
)
recommendation_feedback = table(
    "recommendation_feedback", column("feedback_id", Uuid), column("user_id", Uuid),
    column("recommendation_run_id", Uuid), column("job_posting_id", Uuid), column("feedback", String),
    column("created_at", DateTime(timezone=True)), schema=_SCHEMA,
)
audit_events = table(
    "audit_events", column("actor_user_id", Uuid), column("action_code", String), column("resource_type", String),
    column("resource_id", Uuid), column("request_id", String), column("occurred_at", DateTime(timezone=True)),
    schema=_SCHEMA,
)


class SqlRecommendationFeedbackRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    def lock_feedback(self, user_id: UUID, job_posting_id: UUID) -> None:
        key = literal(f"t47-feedback:{user_id}:{job_posting_id}", String)
        self._db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))

    def is_recommended_to(self, user_id: UUID, job_posting_id: UUID, recommendation_run_id: UUID | None) -> bool:
        r, i = recommendation_runs.c, recommendation_items.c
        # 다른 사람의 실행·추천되지 않은 공고는 모두 False → 라우터에서 404 (존재 여부를 숨김).
        conds = [r.user_id == user_id, i.job_posting_id == job_posting_id]
        if recommendation_run_id is not None:
            conds.append(i.recommendation_run_id == recommendation_run_id)
        joined = recommendation_items.join(recommendation_runs, r.recommendation_run_id == i.recommendation_run_id)
        stmt = select(exists(select(literal(1)).select_from(joined).where(and_(*conds))))
        return bool(self._db.execute(stmt).scalar())

    def latest_feedback(self, user_id: UUID, job_posting_ids: list[UUID]) -> dict[UUID, FeedbackRecord]:
        if not job_posting_ids:
            return {}
        f = recommendation_feedback.c
        # ix_recommendation_feedback_1 (user_id, job_posting_id, created_at DESC)를 탄다.
        stmt = (
            select(f.feedback_id, f.user_id, f.recommendation_run_id, f.job_posting_id, f.feedback, f.created_at)
            .distinct(f.job_posting_id)
            .where(f.user_id == user_id, f.job_posting_id.in_(job_posting_ids))
            .order_by(f.job_posting_id, f.created_at.desc(), f.feedback_id.desc())
        )
        return {
            row.job_posting_id: FeedbackRecord(row.feedback_id, row.user_id, row.recommendation_run_id,
                                               row.job_posting_id, row.feedback, row.created_at)
            for row in self._db.execute(stmt)
        }

    def insert_feedback(self, record: FeedbackRecord) -> None:
        self._db.execute(insert(recommendation_feedback).values(
            feedback_id=record.feedback_id, user_id=record.user_id,
            recommendation_run_id=record.recommendation_run_id, job_posting_id=record.job_posting_id,
            feedback=record.feedback, created_at=record.created_at,
        ))

    def record_audit(self, event: AuditRecord) -> None:
        self._db.execute(insert(audit_events).values(
            actor_user_id=event.actor_user_id, action_code=event.action_code, resource_type=event.resource_type,
            resource_id=event.resource_id, request_id=event.request_id, occurred_at=event.occurred_at,
        ))

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
