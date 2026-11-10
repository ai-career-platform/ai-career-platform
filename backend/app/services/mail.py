"""메일 발송 어댑터 (T93). 실제 메일 공급자는 아직 정해지지 않았습니다(PM 결정 필요).

- 기본값 `UnavailableMailSender`: 발송할 수 없음 → 계정 복구 요청은 모든 사용자에게 같은 503 (계정 존재 여부 비노출)
- `MemoryMailSender`: 시험 전용 outbox. 실제 메일을 보내지 않습니다.
본문·링크·토큰은 로그에 남기지 않습니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class MailDeliveryError(Exception):
    """일시적 발송 실패 (재시도 대상)."""


@dataclass(frozen=True)
class OutgoingMail:
    to: str
    template: str          # 예: password_reset
    link: str


class MailSender(Protocol):
    available: bool

    def send(self, mail: OutgoingMail) -> None: ...


class UnavailableMailSender:
    available = False

    def send(self, mail: OutgoingMail) -> None:  # pragma: no cover - guarded by `available`
        raise MailDeliveryError("mail provider not configured")


@dataclass
class MemoryMailSender:
    """시험용. fail_times 만큼 연속 실패한 뒤 성공합니다."""

    fail_times: int = 0
    outbox: list[OutgoingMail] = field(default_factory=list)
    attempts: int = 0
    available: bool = True

    def send(self, mail: OutgoingMail) -> None:
        self.attempts += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise MailDeliveryError("synthetic delivery failure")
        self.outbox.append(mail)
