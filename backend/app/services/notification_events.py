"""업무 이벤트 → 화면 내(in_app) 알림 연결 (T96 후속). 메일은 보내지 않습니다.

규칙:
- in_app 채널만 다룹니다. 실제 기록은 `NotificationDispatcher`(동의·수신 설정·계정 상태·dedupe_key) 가 합니다.
- T95 매트릭스(`SPECS`)에 **정의된** in_app 유형이고, 이 등록표(`EVENT_TYPES`)에서 승인(`approved=True`)된 이벤트만
  알림을 만듭니다. 매트릭스에 없는 유형·템플릿·동의 코드를 여기서 만들거나 승인하지 않습니다.
- 코드 수준 스위치 `EVENT_NOTIFICATIONS_ENABLED` 기본 꺼짐. 꺼져 있으면 DB 에 아무것도 쓰지 않습니다.
- 알림 실패가 원래 요청(예: 지원 단계 변경)을 실패시키지 않습니다. 로그에는 유형·결과만 남기고 변수·메모는 남기지 않습니다.
- `variables` 에는 개인정보·비밀을 넣지 않습니다(현재 모든 이벤트는 빈 변수).

현재 상태 (2026-11):
- `application.stage_changed` (T102 지원 단계 변경): T95 매트릭스에 유형·템플릿 없음 → **BLOCKED (유형·템플릿 승인 대기)**.
- 후속 hook — 검수(moderation) 결과 알림: 검수 결과 API 가 생기면 `EVENT_TYPES` 에 항목을 추가하고
  (T95 매트릭스·템플릿 승인 후) 해당 서비스에서 `EventNotifier.notify(...)` 를 호출합니다. 지금은 코드 없음.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

from app.services.notifications import SPECS, NotificationDispatcher, NotificationEvent, NotificationSpec

logger = logging.getLogger("app.notifications.events")

EVENT_NOTIFICATIONS_ENABLED = False   # 코드 수준 스위치(환경 변수 아님). PM·법무 승인 전 꺼짐


@dataclass(frozen=True)
class EventType:
    type: str
    source: str          # 이벤트를 내는 기능
    approved: bool       # T95 매트릭스 유형·템플릿·수신 설정이 승인되었는지 (이 파일에서 임의로 True 로 바꾸지 않음)
    note: str


EVENT_TYPES: dict[str, EventType] = {e.type: e for e in (
    EventType("application.stage_changed", "T102 job_applications.update", False,
              "BLOCKED: T95_PREFERENCE_MATRIX.md 에 in_app 유형·템플릿·선택/필수 구분이 정의되지 않음"),
    # 후속: EventType("moderation.result", "<검수 결과 API>", False, "...")  — API 미구현, hook 자리만
)}


class EventNotifier:
    """결과: disabled | unknown_event | blocked_unapproved | blocked_template | error | (dispatcher 결과)."""

    def __init__(self, dispatcher_factory: Callable[[], NotificationDispatcher] | None, *,
                 enabled: bool = EVENT_NOTIFICATIONS_ENABLED, registry: Mapping[str, EventType] = EVENT_TYPES,
                 specs: Mapping[str, NotificationSpec] = SPECS) -> None:
        self.dispatcher_factory, self.enabled, self.registry, self.specs = dispatcher_factory, enabled, registry, specs

    def notify(self, user_id: UUID, type_: str, subject_ref: str) -> str:
        entry = self.registry.get(type_)
        if entry is None:
            return "unknown_event"
        if not self.enabled or self.dispatcher_factory is None:
            return "disabled"
        spec = self.specs.get(type_)
        if not entry.approved or spec is None or spec.channel != "in_app":
            logger.info("event notification blocked type=%s reason=unapproved", type_)
            return "blocked_unapproved"
        try:
            result = self.dispatcher_factory().enqueue(NotificationEvent(user_id, type_, subject_ref, {}))
        except ValueError:   # 템플릿 미승인·변수 불일치 (T95 §7)
            logger.info("event notification blocked type=%s reason=template", type_)
            return "blocked_template"
        except Exception:    # noqa: BLE001 — 알림 실패가 원래 요청을 깨지 않도록
            logger.warning("event notification failed type=%s", type_)
            return "error"
        logger.info("event notification type=%s result=%s", type_, result)
        return result
