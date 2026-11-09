"""T47 추천 피드백 서비스 (FR-ANL-004, F-018). HTTP·DB 수명주기와 무관하다.

규칙 (docs/API_CONTRACT.md §1.3, database/DATA_DICTIONARY.md D07)
- 소유권: 피드백은 **내 추천 실행에 들어 있던 공고**에만 남길 수 있다.
  `recommendation_run_id`를 주면 그 실행이 내 것이고 그 실행에 공고가 있어야 한다.
  다른 사람의 실행, 없는 실행, 추천된 적 없는 공고는 모두 404 NOT_FOUND (403을 쓰지 않아 존재를 숨김).
- 이력: 추가만 한다. 공고별 최신 행이 현재 피드백이다.
- 중복: 보낸 값이 현재(최신) 값과 같으면 새 행을 만들지 않고 최신 행을 그대로 돌려준다(멱등, 201).
  다른 추천 실행에서 같은 값을 다시 눌러도 같다(현재 상태가 바뀌지 않으므로).
- 정정: 값을 바꾸거나 `cleared`(취소)를 보내면 새 행을 추가한다. 이후 최신 값이 이긴다.
  새 행의 created_at은 직전 행보다 항상 뒤다(시계가 뒤로 가도 `max(시계, 직전 + 1µs)`, 잠금 안에서 계산).
  기록이 없는 상태의 `cleared`도 행 1개를 남긴다(응답에 feedback_id가 필요하고, "취소함" 의사도 이력이다).
- 감사: 새 행을 추가할 때만 같은 트랜잭션에서 `audit_events`에 `user.recommendation_feedback.create`를 남긴다.
  멱등 처리(새 행 없음)는 데이터가 바뀌지 않았으므로 남기지 않는다. 피드백 값·공고 정보는 감사 행에 넣지 않는다.
- 피드백은 내 추천 개선에만 쓴다. 기업·채용 담당자에게 공유하지 않는다.
"""

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.recommendation_feedback import AuditRecord, FeedbackRecord, RecommendationFeedbackRepository
from app.schemas.recommendation_feedback import CurrentFeedback, RecommendationFeedback, RecommendationFeedbackInput

AUDIT_ACTION = "user.recommendation_feedback.create"
AUDIT_RESOURCE = "recommendation_feedback"
_TICK = timedelta(microseconds=1)  # timestamptz 해상도


def _dto(record: FeedbackRecord) -> RecommendationFeedback:
    return RecommendationFeedback(feedback_id=record.feedback_id, job_posting_id=record.job_posting_id,
                                  feedback=record.feedback, created_at=record.created_at)


class RecommendationFeedbackService:
    def __init__(
        self,
        repo: RecommendationFeedbackRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_id: Callable[[], UUID] = uuid.uuid4,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._new_id = new_id

    def create(self, user_id: UUID, body: RecommendationFeedbackInput, request_id: str | None) -> RecommendationFeedback:
        try:
            self._repo.lock_feedback(user_id, body.job_posting_id)
            if not self._repo.is_recommended_to(user_id, body.job_posting_id, body.recommendation_run_id):
                raise AppError(ErrorCode.NOT_FOUND, log_detail="posting not in caller's recommendation runs")
            latest = self._repo.latest_feedback(user_id, [body.job_posting_id]).get(body.job_posting_id)
            if latest is not None and latest.feedback == body.feedback:
                self._repo.rollback()  # 잠금만 풀고 아무것도 쓰지 않는다
                return _dto(latest)
            # 현재 값은 created_at DESC로 정한다. 앱 서버 시계가 뒤로 가거나 인스턴스끼리 어긋나도
            # 정정이 항상 최신 행이 되도록, 잠금 안에서 직전 행보다 최소 1µs 뒤로 맞춘다.
            now = self._clock()
            if latest is not None and now <= latest.created_at:
                now = latest.created_at + _TICK
            record = FeedbackRecord(
                feedback_id=self._new_id(), user_id=user_id, recommendation_run_id=body.recommendation_run_id,
                job_posting_id=body.job_posting_id, feedback=body.feedback, created_at=now,
            )
            self._repo.insert_feedback(record)
            self._repo.record_audit(AuditRecord(
                actor_user_id=user_id, action_code=AUDIT_ACTION, resource_type=AUDIT_RESOURCE,
                resource_id=record.feedback_id, request_id=request_id, occurred_at=now,
            ))
            self._repo.commit()
            return _dto(record)
        except Exception:
            self._repo.rollback()
            raise

    # ------------------------------------------------------------- T45 연동용 (공개 API 아님)
    def current_feedback(self, user_id: UUID, job_posting_ids: Iterable[UUID]) -> dict[UUID, CurrentFeedback | None]:
        """T45 `RecommendationItem.feedback` 채우기용. 공고별 내 최신 피드백, 없거나 cleared면 None."""
        ids = list(dict.fromkeys(job_posting_ids))
        latest = self._repo.latest_feedback(user_id, ids)
        result: dict[UUID, CurrentFeedback | None] = {}
        for posting_id in ids:
            row = latest.get(posting_id)
            result[posting_id] = None if row is None or row.feedback == "cleared" else row.feedback  # type: ignore[assignment]
        return result

    def not_interested_ids(self, user_id: UUID, job_posting_ids: Iterable[UUID]) -> set[UUID]:
        """다음 추천에서 뺄 공고 (최신 값이 not_interested, D07 규칙 · FR-ANL-004 수용 기준 3)."""
        return {pid for pid, value in self.current_feedback(user_id, job_posting_ids).items()
                if value == "not_interested"}
