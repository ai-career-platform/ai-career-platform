"""T81 PM 결정 이후 `POST /admin/company-postings/{id}/decision` 은 효과 없이 409 다(결정은 검수 건으로만).

T125 전이 자체(CompanyPostingService.decide — 검수 결정이 같은 트랜잭션에서 부르는 함수)를 시험하는 T126·T148 시험은
이 도우미로 서비스를 직접 부르고, HTTP 응답과 같은 모양(status_code·json())으로 결과를 받는다.
"""
from __future__ import annotations

import json
from uuid import UUID

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.routers.company_postings import _out
from tests.conftest import TEST_SECRET


class Result:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code, self._body = status_code, body

    def json(self) -> dict:
        return self._body

    @property
    def text(self) -> str:
        return json.dumps(self._body, ensure_ascii=False)


def user_of(headers: dict[str, str]) -> UUID:
    return decode_access_token(TEST_SECRET, headers["Authorization"].split(" ", 1)[1]).user_id


def call_decide(service, user_id: UUID, roles, posting: dict, decision: str = "approve", **extra) -> Result:
    try:
        moved = service.decide(user_id, frozenset(roles), UUID(posting["posting_id"]), decision,
                               extra.get("reason_code"), extra.get("note"), posting["version"])
    except AppError as exc:
        return Result(exc.status, {"code": str(exc.code), "status": exc.status})
    return Result(200, _out(moved).model_dump(mode="json"))
