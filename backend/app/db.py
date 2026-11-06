from collections.abc import Iterator

import psycopg
from fastapi import HTTPException, Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DatabaseSettings


def create_db_engine(settings: DatabaseSettings) -> Engine:
    """앱 수명 동안 재사용하는 SQLAlchemy 엔진(연결 풀 포함). 첫 사용 시점에 접속합니다."""

    def connect() -> psycopg.Connection:
        # 접속 실패 메시지에 자격정보가 남지 않도록 드라이버 경계에서 정제합니다.
        try:
            return psycopg.connect(settings.url, connect_timeout=settings.timeout)
        except psycopg.OperationalError:
            raise psycopg.OperationalError("PostgreSQL connection failed") from None

    return create_engine(
        "postgresql+psycopg://",
        creator=connect,
        pool_size=settings.pool_size,
        max_overflow=0,
        pool_timeout=settings.timeout,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: 커밋 뒤에도 응답 직렬화(Pydantic)에서 ORM 객체를 읽을 수 있게 합니다.
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """요청마다 Session 하나를 제공한다. 성공한 쓰기의 commit은 호출자가 담당한다."""
    factory = request.app.state.db_session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    session = factory()
    try:
        yield session
    except (OperationalError, PoolTimeoutError):
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    finally:
        # 남은 트랜잭션은 롤백되고 연결은 풀로 반환됩니다.
        session.close()
