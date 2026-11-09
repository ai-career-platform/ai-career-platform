"""T47 추천 피드백 DB 접근 (database/DATA_DICTIONARY.md D05~D07, F11, 스키마 `career`).

- 서비스는 `RecommendationFeedbackRepository` 프로토콜에만 의존한다. 테스트는 `tests/fakes.py`의 메모리 구현을 쓴다.
- 추천 실행·항목(`recommendation_runs`/`recommendation_items`)은 T45(`app/repositories/recommendation_runs.py`)가
  쓴다. 여기서는 소유권 확인에 필요한 SELECT만 하며, 테이블 정의는 T45와 같은 `recommendation_tables.py`를 쓴다.
- 공고별 최신 피드백 조회(`latest_feedback_records`)와 현재 값 규칙(`current_feedback_values`)은 모듈 함수로 두어
  T45가 `RecommendationItem.feedback` 채우기·`not_interested` 제외에 그대로 쓴다(같은 규칙을 한 곳에서만 정한다).
- `recommendation_feedback`은 추가만 한다(D07). 공고별 최신 행이 현재 피드백이다.
- 쓰기는 서비스가 `commit()`을 호출해야 확정된다 (T15 `AuthRepository`와 같은 규칙).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid, and_, column, exists, func, insert, literal, select, table
from sqlalchemy.orm import Session

from app.repositories.recommendation_tables import SCHEMA
from app.repositories.recommendation_tables import feedback as recommendation_feedback
from app.repositories.recommendation_tables import items as recommendation_items
from app.repositories.recommendation_tables import runs as recommendation_runs
from app.schemas.recommendation_feedback import CurrentFeedback


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


audit_events = table(
    "audit_events", column("actor_user_id", Uuid), column("action_code", String), column("resource_type", String),
    column("resource_id", Uuid), column("request_id", String), column("occurred_at", DateTime(timezone=True)),
    schema=SCHEMA,
)


def latest_feedback_records(db: Session, user_id: UUID, job_posting_ids: Iterable[UUID]) -> dict[UUID, FeedbackRecord]:
    """공고별 이 사용자의 최신 피드백 행 (`created_at DESC, feedback_id DESC`). 기록이 없는 공고는 결과에 없다.

    T47 서비스(중복·정정 판정)와 T45 저장소(항목 feedback·not_interested 제외)가 함께 쓴다.
    """
    ids = list(dict.fromkeys(job_posting_ids))
    if not ids:
        return {}
    f = recommendation_feedback.c
    # ix_recommendation_feedback_1 (user_id, job_posting_id, created_at DESC)를 탄다.
    stmt = (
        select(f.feedback_id, f.user_id, f.recommendation_run_id, f.job_posting_id, f.feedback, f.created_at)
        .distinct(f.job_posting_id)
        .where(f.user_id == user_id, f.job_posting_id.in_(ids))
        .order_by(f.job_posting_id, f.created_at.desc(), f.feedback_id.desc())
    )
    return {
        row.job_posting_id: FeedbackRecord(row.feedback_id, row.user_id, row.recommendation_run_id,
                                           row.job_posting_id, row.feedback, row.created_at)
        for row in db.execute(stmt)
    }


def current_feedback_values(latest: Mapping[UUID, FeedbackRecord],
                            job_posting_ids: Iterable[UUID] | None = None) -> dict[UUID, CurrentFeedback | None]:
    """최신 행 → T45 `RecommendationItem.feedback` 값. 기록 없음·`cleared`는 None(계약상 null).

    `job_posting_ids`를 주면 그 순서(중복 제거)로 모든 공고를 담고, 생략하면 `latest`의 공고만 담는다.
    """
    ids = list(dict.fromkeys(latest if job_posting_ids is None else job_posting_ids))
    result: dict[UUID, CurrentFeedback | None] = {}
    for posting_id in ids:
        row = latest.get(posting_id)
        result[posting_id] = None if row is None or row.feedback == "cleared" else row.feedback  # type: ignore[assignment]
    return result


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
        return latest_feedback_records(self._db, user_id, job_posting_ids)

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
