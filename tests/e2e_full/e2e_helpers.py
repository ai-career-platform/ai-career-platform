"""Full-system E2E helper (TEST ONLY) — 브라우저 시나리오 중간에 부르는 1회용 명령.

  python e2e_helpers.py submit-case <posting_id> <submitted_by_user_id>
      기업 공고 검수 건을 앱 코드(ModerationService.submit, T81)로 만든다. 현재 스택(35fe589)은 기업 공고 검수 요청 때
      검수 건을 자동으로 만들지 않으므로(PR #359 후속 커밋 대기) 관리자 화면 흐름을 시험하려고 fixture 로 만든다.
      결과 JSON: {"case_id": ..., "status": ...}

DATABASE_URL·JWT_SECRET 은 E2E API 프로세스와 같은 env 를 받는다(최소 권한 앱 역할).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


def submit_case(posting_id: str, submitted_by: str) -> dict:
    from sqlalchemy.orm import Session

    from app.core.auth_config import AuthSettings
    from app.core.config import get_settings
    from app.db import create_db_engine
    from app.repositories.moderation import SqlModerationRepository
    from app.services import moderation as mod
    from app.services.job_postings import ListCursor, derive_cursor_key

    settings = get_settings()
    secret = AuthSettings.from_env(settings.app_env).jwt_secret
    engine = create_db_engine(settings.database)
    try:
        with Session(engine) as session:
            service = mod.ModerationService(SqlModerationRepository(session), ListCursor(derive_cursor_key(secret)), {})
            case = service.submit("company_posting", UUID(posting_id), "PRE_PUBLISH", submitted_by=UUID(submitted_by),
                                  content_owner_id=UUID(submitted_by))
            session.commit()
            return {"case_id": str(case.case_id), "status": case.status}
    finally:
        engine.dispose()


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "submit-case":
        print(json.dumps(submit_case(*args)))
    else:
        raise SystemExit(f"unknown command {command}")
