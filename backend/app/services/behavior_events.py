"""T72 동의 기반 행동 이벤트 수집 (docs/data/BEHAVIOR_EVENT_CONTRACT.md, F-025).

처리 순서: 인증(라우터 의존성) → 입력 검증(DTO) → 수집 스위치 → Rate Limit → 시각 범위 →
사용자 행 잠금(T31·T71과 같은 순서) → 계정 상태 → 최신 동의 → 저장 → Commit.

- 서버 수집 스위치(`BEHAVIOR_EVENTS_ENABLED`)는 기본 꺼짐. 꺼져 있으면 DB에 접근하지 않는다.
- personalization 이벤트 3종은 T71 미승인 제안이라 형식만 검사하고 저장하지 않는다.
- 중복 방지: 저장 기본키 = uuid5(namespace, "user_id:클라이언트 event_id"). 클라이언트 값을 기본키에
  그대로 넣지 않고, 사용자가 다르면 키가 달라 서로의 이벤트를 덮거나 확인할 수 없다.
- 이벤트 발생 시각이 최신 동의 시각보다 이르면 저장하지 않는다. 철회(삭제) 후 재동의하고 예전
  이벤트를 다시 보내도 삭제된 이벤트가 복원되지 않는다.
"""
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import AttemptLimiter
from app.schemas.behavior_events import (
    TRACKING_POLICY, BehaviorEventInput, BehaviorEventResult, event_at_window_error,
)

# 고정 namespace. 바꾸면 이미 저장된 이벤트와 중복 판정이 어긋나므로 바꾸지 않는다.
EVENT_KEY_NAMESPACE = uuid.UUID("6f2b8c1e-7d4a-5e9b-8c3f-72a1b4d0e5c6")


def storage_event_id(user_id: uuid.UUID, client_event_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(EVENT_KEY_NAMESPACE, f"{user_id}:{client_event_id}")


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class BehaviorEventSettings:
    """운영값은 미확정이다. 기본은 수집 꺼짐·Rate Limit 없음."""

    enabled: bool = False
    rate_limit: RateLimit | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "BehaviorEventSettings":
        enabled = environ.get("BEHAVIOR_EVENTS_ENABLED", "").strip().lower() in {"1", "true", "yes"}
        raw = environ.get("BEHAVIOR_EVENTS_RATE_LIMIT", "").strip()  # 예: "60/60" = 60초에 60건
        rate_limit = None
        if raw:
            count, _, seconds = raw.partition("/")
            if not (count.isdigit() and seconds.isdigit() and int(count) > 0 and int(seconds) > 0):
                raise ValueError("BEHAVIOR_EVENTS_RATE_LIMIT must look like <count>/<seconds>")
            rate_limit = RateLimit(int(count), int(seconds))
        return cls(enabled=enabled, rate_limit=rate_limit)


class BehaviorEventService:
    def __init__(self, repo, settings: BehaviorEventSettings, limiter: AttemptLimiter,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.repo = repo
        self.settings = settings
        self.limiter = limiter
        self.clock = clock

    def _check_rate_limit(self, user_id: uuid.UUID) -> None:
        rule = self.settings.rate_limit
        if rule is None:
            return
        key = f"behavior-events:{user_id}"
        retry = self.limiter.retry_after(key)
        if not retry:
            # AttemptLimiter는 limit번째 기록에서 잠근다 → limit+1 로 넘겨 limit건까지 허용
            retry = self.limiter.hit(key, rule.limit + 1, rule.window_seconds)
        if retry:
            raise AppError(ErrorCode.RATE_LIMITED, retry_after=retry, log_detail="behavior event rate limit")

    def record(self, user_id: uuid.UUID, body: BehaviorEventInput) -> BehaviorEventResult:
        def result(status: str) -> BehaviorEventResult:
            return BehaviorEventResult(event_id=body.event_id, status=status)

        if not self.settings.enabled:
            return result("collection_disabled")
        self._check_rate_limit(user_id)
        if event_at_window_error(body.event_at, self.clock()):
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="event_at outside accepted window")
        if not body.is_tracking:
            return result("blocked_policy_pending")
        try:
            user = self.repo.lock_user(user_id)
            if user is None or user.status != "active":
                raise AppError(ErrorCode.UNAUTHENTICATED, log_detail="user missing or disabled")
            consent = self.repo.latest_consent(user_id, TRACKING_POLICY)
            if consent is None or not consent.granted or body.event_at < consent.recorded_at:
                self.repo.rollback()
                return result("blocked_no_consent")
            inserted = self.repo.insert_event(
                storage_event_id(user_id, body.event_id), user_id, body.event_code, body.event_at, body.metadata)
            self.repo.commit()
            return result("recorded" if inserted else "duplicate")
        except AppError:
            self.repo.rollback()
            raise
        except SQLAlchemyError as exc:
            self.repo.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except Exception:
            self.repo.rollback()
            raise
