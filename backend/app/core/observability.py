"""T112 관측 계약 — 요청 단위 구조화 로그·기본 지표·Access Log Query String 제거.

원칙
- 로그에는 **Query String·요청 본문·헤더 값(Authorization, Cookie)·이메일·토큰을 넣지 않는다.**
  경로만 남기고, 경로 안의 이메일·긴 토큰 모양 구간은 가린다.
- `request_id` 는 RequestIdMiddleware 가 정한 값을 그대로 쓴다(응답 헤더·오류 본문·감사 기록과 같은 값).
- 이 모듈은 로그 수집기·보존 설정을 바꾸지 않는다. `app.access` 로거는 INFO 라서, 운영 로그 설정(uvicorn
  --log-config)에서 켜기 전에는 출력되지 않는다(기본 비활성). 켜는 것은 PM 승인 후(docs/ops/OBSERVABILITY.md).
- 기존 uvicorn access log 에는 필터를 달아 Query String 만 제거한다(출력 여부·형식은 그대로).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Message, Receive, Scope, Send

ACCESS_LOGGER = "app.access"
access_logger = logging.getLogger(ACCESS_LOGGER)

# 지연 분포 구간(ms). p95 계산이 아니라 구간별 개수 — 수집기 없이도 비교 가능한 최소 지표
LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000)

_EMAIL = re.compile(r"[^/@\s]+@[^/@\s]+")
_TOKENISH = re.compile(r"^[A-Za-z0-9_\-.~%]{40,}$")


QUERY_MARK = "?[query redacted]"


def safe_path(path: str, mark_query: bool = False) -> str:
    """경로에서 Query String 을 떼고, 이메일·긴 토큰 모양 구간을 가린다. UUID(36자)는 남긴다.

    mark_query=True 이면 Query 가 있었다는 사실만 `?[query redacted]` 로 남긴다(T86 F-1 개선안 표기와 같음).
    """
    had_query = "?" in path
    path = path.split("?", 1)[0]
    parts = []
    for part in path.split("/"):
        if _EMAIL.search(part):
            parts.append(":email")
        elif _TOKENISH.match(part):
            parts.append(":token")
        else:
            parts.append(part)
    return "/".join(parts) + (QUERY_MARK if mark_query and had_query else "")


@dataclass
class RequestMetrics:
    """프로세스 안 누적 지표. 외부로 노출하는 엔드포인트는 만들지 않는다(승인 전)."""

    requests: Counter = field(default_factory=Counter)        # (method, status_class) → 건수
    latency: Counter = field(default_factory=Counter)         # 구간 상한(ms) 또는 'inf' → 건수
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def observe(self, method: str, status: int, duration_ms: float) -> None:
        bucket: int | str = next((b for b in LATENCY_BUCKETS_MS if duration_ms <= b), "inf")
        with self._lock:
            self.requests[(method, f"{status // 100}xx")] += 1
            self.latency[bucket] += 1

    def snapshot(self) -> dict:
        with self._lock:
            total = sum(self.requests.values())
            errors = sum(v for (_, cls), v in self.requests.items() if cls == "5xx")
            return {
                "requests_total": total,
                "by_status_class": {cls: sum(v for (_, c), v in self.requests.items() if c == cls)
                                    for cls in sorted({c for _, c in self.requests})},
                "error_rate_5xx": (errors / total) if total else 0.0,
                "latency_buckets_ms": {str(k): self.latency[k] for k in (*LATENCY_BUCKETS_MS, "inf")},
            }


class AccessLogMiddleware:
    """요청 1건당 구조화 로그 1줄 + 지표 누적. RequestIdMiddleware 안쪽에 둔다(request_id 를 읽음)."""

    def __init__(self, app: ASGIApp, metrics: RequestMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            status = status_holder["status"]
            method = scope.get("method", "")
            self.metrics.observe(method, status, duration_ms)
            request_id = (scope.get("state") or {}).get("request_id", "-")
            access_logger.info(
                "http_request request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id, method, safe_path(scope.get("path", "")), status, duration_ms,
            )


class StripQueryFilter(logging.Filter):
    """uvicorn.access 레코드(args: client, method, full_path, http_version, status)에서 Query String 제거.

    T86 Finding F-1(접근 로그에 조회 조건·사용자 ID 원문)의 개선안 프로토타입을 앱에 적용한 것.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], safe_path(args[2], mark_query=True), *args[3:])
        return True


def install_uvicorn_access_filter() -> None:
    target = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, StripQueryFilter) for f in target.filters):
        target.addFilter(StripQueryFilter())
