"""T142 반출 묶음 worker, 명시적 1회 실행: python -m app.personal_data_worker [--limit N]

재시도(failed → received, 한도 안) → received 를 최대 N건 처리 → 24시간 지난 묶음 만료·지난 토큰 정리.
API 기동 중에는 아무것도 돌지 않고, 이 저장소는 스케줄(Timer·Cron)을 만들지 않습니다(운영 실행은 별도 승인).
출력·로그에는 개수만 남깁니다(사용자·요청 식별자·내용 없음).
"""
import argparse
import logging

from app.core.config import get_settings
from app.db import create_db_engine, create_session_factory
from app.routers.personal_data_requests import build_sql_service
from app.services.personal_data_requests import PersonalDataRequestService


def run_once(service: PersonalDataRequestService, limit: int = 20) -> dict[str, int]:
    return service.run_once(limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T142 personal data export worker (one shot)")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.database is None:
        raise SystemExit("DATABASE_URL is required")
    engine = create_db_engine(settings.database)
    try:
        with create_session_factory(engine)() as session:
            counts = run_once(build_sql_service(session), max(1, min(args.limit, 200)))
    finally:
        engine.dispose()
    logging.getLogger(__name__).info("personal data worker done %s", counts)
    print(counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
