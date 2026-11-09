"""로그인·가입 시도 제한 (API_CONTRACT §1.2, FR-ACC-002 수용 기준 3).

프로세스 메모리 기반의 이동 창(sliding window) 카운터다. 워커가 여러 개이거나 재시작하면
카운트가 공유·유지되지 않는다 → 다중 인스턴스 배포 전에 공유 저장소(T110 등)로 교체 필요.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class AttemptLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """잠겨 있으면 남은 초, 아니면 0."""
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            remaining = until - self._clock()
            if remaining <= 0:
                del self._locked_until[key]
                return 0
            return max(1, math.ceil(remaining))

    def hit(self, key: str, limit: int, window: int, lock_seconds: int | None = None) -> int:
        """시도 1회를 기록한다. 한도를 넘으면 잠그고 남은 초를 돌려준다(아니면 0)."""
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= now - window:
                events.popleft()
            events.append(now)
            if len(events) >= limit:
                duration = lock_seconds if lock_seconds is not None else window
                self._locked_until[key] = now + duration
                events.clear()
                return duration
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
            self._locked_until.pop(key, None)
