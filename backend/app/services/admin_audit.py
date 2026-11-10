"""T84 운영 감사·AI 사용량 조회 서비스. HTTP·DB 수명주기와 무관하다.

확정 계약(docs/api/openapi.yaml `listAuditEvents`·`getAiUsage`)만 운영 경로에서 쓴다.
PM 승인 전 결정(D1~D5, docs/security/T84_AUDIT_USAGE_API_READINESS.md §13)은 `PROPOSED_POLICY`와
`*_proposed` 메서드로만 구현·시험하고, 운영 라우터는 항상 `CONFIRMED_POLICY`를 쓴다.

감사 목록 처리 순서 (readiness §11, 한 트랜잭션)
1. 권한 확인 (라우터 의존성)  2. 조건 검증  3. 결과 범위 확정: 첫 페이지에서 as_of=DB now(),
   상한 = min(to, as_of) 를 서명된 cursor에 넣어 다음 페이지도 같은 상한을 씀
4~5. (PROPOSED) 첫 페이지면 admin.audit.view 1행 INSERT·성공 확인 — 실패 시 503
6. 목록 SELECT (자기 조회 행 제외) → 응답

알려진 한계: occurred_at 은 쓰는 쪽 트랜잭션의 시작 시각이라, 순회 중에 늦게 커밋된 '과거 시각' 행은
그 순회에서 보이지 않을 수 있다(새로 조회하면 보임). T83 recorded_at/audit_seq Migration 후 해결.

로그: 필터 값(특히 사용자 ID)은 log_detail 에 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import AttemptLimiter
from app.repositories.admin_audit import AdminAuditRepository, AuditFilter, AuditRow, UsageRow
from app.schemas.admin_audit import (
    AiUsageAmounts, AiUsageBucket, AiUsageReport, AiUsageReportBucket, AuditEvent, AuditEventView,
)
from app.services.job_postings import ListCursor

KST = timezone(timedelta(hours=9), "Asia/Seoul")   # 한국은 일광절약시간이 없어 고정 오프셋과 같다
CURSOR_KIND = "admin-audit-events"
MASKED_RESOURCE_TYPES = frozenset({"user"})         # D3 PROPOSED
_MICRO = Decimal("0.000001")


@dataclass(frozen=True)
class AdminQueryPolicy:
    """조회 보호 정책. 기본값(None/False)은 확정 계약에 있는 규칙만 적용한다."""

    max_range_days: int | None = None            # D5
    record_reads: bool = False                   # D4
    rate_limit_per_minute: int | None = None     # 제안 (기존 계약 없음)
    statement_timeout_ms: int | None = None      # 제안 (기존 계약 없음)
    usage_requires_audit_read: bool = False      # D1
    max_usage_buckets: int | None = None         # 제안


CONFIRMED_POLICY = AdminQueryPolicy()
# PROPOSED — PM 승인 전. 운영 라우터에서 쓰지 않는다 (tests/test_t84_admin_audit.py 가 고정).
PROPOSED_POLICY = AdminQueryPolicy(max_range_days=90, record_reads=True, rate_limit_per_minute=60,
                                   statement_timeout_ms=5000, usage_requires_audit_read=True,
                                   max_usage_buckets=200)


def _invalid(detail: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_FAILED, log_detail=detail)


def _db_unavailable(exc: Exception) -> AppError:
    return AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=f"admin audit db error: {type(exc).__name__}")


# ---------------------------------------------------------------- masking (D3 PROPOSED)
def mask_uuid(value: UUID | None) -> str | None:
    """앞 8자리 + 끝 4자리만 남긴다. 화면 노출을 줄이는 용도일 뿐 **익명화가 아니다**
    (48비트가 남아 사용자 목록과 대조할 수 있음). 마스킹 값은 검색 조건으로 받지 않는다."""
    if value is None:
        return None
    h = value.hex
    return f"{h[:8]}-****-****-****-********{h[-4:]}"


def to_view(row: AuditRow) -> AuditEventView:
    masked = row.resource_type in MASKED_RESOURCE_TYPES and row.resource_id is not None
    return AuditEventView(
        audit_event_id=row.audit_event_id,
        actor_user_id_masked=mask_uuid(row.actor_user_id),
        action_code=row.action_code,
        resource_type=row.resource_type,
        resource_id=mask_uuid(row.resource_id) if masked else (str(row.resource_id) if row.resource_id else None),
        resource_id_masked=masked,
        request_id=row.request_id,
        occurred_at=row.occurred_at,
    )


def to_event(row: AuditRow) -> AuditEvent:
    return AuditEvent(**row.__dict__)


@dataclass(frozen=True)
class AuditPage:
    rows: list[AuditRow]
    next_cursor: str | None
    read_event_id: UUID | None   # PROPOSED 감사 조회 기록 id (기록하지 않았으면 None)


class AdminAuditService:
    def __init__(self, repo: AdminAuditRepository, cursor: ListCursor, policy: AdminQueryPolicy = CONFIRMED_POLICY,
                 limiter: AttemptLimiter | None = None) -> None:
        self.repo, self.cursor, self.policy, self.limiter = repo, cursor, policy, limiter

    # ------------------------------------------------------------ common guards
    def _rate_limit(self, user_id: UUID) -> None:
        per_minute = self.policy.rate_limit_per_minute
        if per_minute is None or self.limiter is None:
            return
        key = f"admin-read:{user_id}"
        if wait := self.limiter.retry_after(key):
            raise AppError(ErrorCode.RATE_LIMITED, retry_after=wait)
        if wait := self.limiter.hit(key, per_minute + 1, 60):
            raise AppError(ErrorCode.RATE_LIMITED, retry_after=wait)

    def _timeout(self) -> None:
        if self.policy.statement_timeout_ms is not None:
            self.repo.set_statement_timeout(self.policy.statement_timeout_ms)

    def require_usage_permission(self, permissions: frozenset[str]) -> None:
        if self.policy.usage_requires_audit_read and "admin.audit.read" not in permissions:
            raise AppError(ErrorCode.FORBIDDEN, log_detail="requires admin.audit.read (D1 proposed)")

    # ------------------------------------------------------------ audit events
    def list_events(self, user_id: UUID, *, start: datetime, end: datetime, actor_user_id: UUID | None = None,
                    action_code: str | None = None, resource_type: str | None = None,
                    request_id: str | None = None, limit: int = 20, cursor: str | None = None,
                    call_request_id: str | None = None) -> AuditPage:
        # 2. 조건 검증
        self._rate_limit(user_id)
        if start.tzinfo is None or end.tzinfo is None:
            raise _invalid("from/to need a UTC offset")
        if start >= end:
            raise _invalid("from must be earlier than to")
        if self.policy.max_range_days is not None and end - start > timedelta(days=self.policy.max_range_days):
            raise _invalid("audit range too long")
        if not 1 <= limit <= 100:
            raise _invalid("limit out of range")
        params = {"from": start.astimezone(UTC).isoformat(), "to": end.astimezone(UTC).isoformat(),
                  "actor_user_id": str(actor_user_id) if actor_user_id else None, "action_code": action_code,
                  "resource_type": resource_type, "request_id": request_id}
        after = None
        if cursor is not None:
            last_id, raw = self.cursor.decode(cursor, CURSOR_KIND, params)
            try:
                at_raw, upper_raw = (raw or "").split("|")
                after, upper = (datetime.fromisoformat(at_raw), last_id), datetime.fromisoformat(upper_raw)
            except ValueError:
                raise AppError(ErrorCode.INVALID_CURSOR, log_detail="audit cursor position unparsable") from None
        try:
            self._timeout()
            if cursor is None:
                # 3. 결과 범위 확정
                upper = min(end, self.repo.now())
            read_id = None
            if cursor is None and self.policy.record_reads:
                # 4~5. PROPOSED: 첫 페이지 감사 조회 기록. 실패하면 결과를 돌려주지 않는다 (fail-closed).
                try:
                    read_id, _ = self.repo.record_read(user_id, call_request_id)
                except SQLAlchemyError as exc:
                    raise _db_unavailable(exc) from None
            # 6. 목록 SELECT
            flt = AuditFilter(start, upper, actor_user_id, action_code, resource_type, request_id)
            rows = self.repo.list_events(flt, after, read_id, limit + 1)
            if read_id is not None:
                self.repo.commit()
        except OperationalError as exc:
            raise _db_unavailable(exc) from None
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = self.cursor.encode(CURSOR_KIND, params, last.audit_event_id,
                                             f"{last.occurred_at.isoformat()}|{upper.isoformat()}")
        return AuditPage(page, next_cursor, read_id)

    # ------------------------------------------------------------ AI usage
    def _usage_rows(self, user_id: UUID, date_from: date, date_to: date, group_by: str, *,
                    proposed_cost: bool, cost_known_since: datetime | None) -> list[UsageRow]:
        self._rate_limit(user_id)
        if date_from > date_to:
            raise _invalid("from must not be after to")
        if self.policy.max_range_days is not None and (date_to - date_from).days + 1 > self.policy.max_range_days:
            raise _invalid("usage range too long")
        # from·to 는 KST 날짜, 양쪽 포함 → [from 00:00 KST, to+1 00:00 KST)
        start = datetime.combine(date_from, time(0), KST)
        end = datetime.combine(date_to + timedelta(days=1), time(0), KST)
        try:
            self._timeout()
            rows = self.repo.usage(group_by, start, end, proposed_cost=proposed_cost,
                                   cost_known_since=cost_known_since)
        except OperationalError as exc:
            raise _db_unavailable(exc) from None
        if self.policy.max_usage_buckets is not None and len(rows) > self.policy.max_usage_buckets:
            raise _invalid("too many usage buckets")
        return rows

    def usage(self, user_id: UUID, date_from: date, date_to: date, group_by: str) -> list[AiUsageBucket]:
        """확정 계약 응답. 비용은 **저장된 추정값의 합**이며 검증되지 않았다(D2 미승인) → 라우터가 헤더로 표시.

        비용이 NULL 인 행이 생기면(D2 Migration 이후) 확정 계약으로는 표현할 수 없으므로 0으로 바꾸지 않고 실패한다.
        """
        rows = self._usage_rows(user_id, date_from, date_to, group_by, proposed_cost=False, cost_known_since=None)
        if any(r.cost_sum is None for r in rows):
            raise AppError(ErrorCode.INTERNAL_ERROR, log_detail="NULL cost under confirmed contract; adopt D2 report")
        return [AiUsageBucket(key=r.key, input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                              estimated_cost_usd=float(r.cost_sum.quantize(_MICRO, ROUND_HALF_UP)),
                              request_count=r.request_count) for r in rows]

    def usage_report_proposed(self, user_id: UUID, date_from: date, date_to: date, group_by: str,
                              cost_known_since: datetime | None = None) -> AiUsageReport:
        """PROPOSED(D2) 응답. 경계 시각 이전 행·NULL 행은 비용 미확인으로 세고 0으로 더하지 않는다.
        `cost_known_since` 가 없으면(D2 Migration 전) 모든 행이 미확인 → 비용은 null."""
        rows = self._usage_rows(user_id, date_from, date_to, group_by, proposed_cost=True,
                                cost_known_since=cost_known_since)

        def money(value: Decimal | None) -> float | None:
            return None if value is None else float(value.quantize(_MICRO, ROUND_HALF_UP))

        buckets = [AiUsageReportBucket(key=r.key, request_count=r.request_count, input_tokens=r.input_tokens,
                                       output_tokens=r.output_tokens, estimated_cost_usd=money(r.cost_sum),
                                       unpriced_request_count=r.unpriced_request_count) for r in rows]
        priced = [r.cost_sum for r in rows if r.cost_sum is not None]
        totals = AiUsageAmounts(
            request_count=sum(r.request_count for r in rows), input_tokens=sum(r.input_tokens for r in rows),
            output_tokens=sum(r.output_tokens for r in rows), estimated_cost_usd=money(sum(priced)) if priced else None,
            unpriced_request_count=sum(r.unpriced_request_count for r in rows))
        return AiUsageReport(from_=date_from, to=date_to, group_by=group_by, buckets=buckets, totals=totals)
