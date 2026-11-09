from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, ExceptionContext, make_url
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DatabaseSettings
from app.core.errors import AppError, ErrorCode

# SQLAlchemy 방언+드라이버 이름. 드라이버 라이브러리는 코드에서 직접 import하지 않고 SQLAlchemy가 불러온다.
DB_DRIVERNAME = "postgresql+psycopg"


def sqlalchemy_url(url: str) -> URL:
    """`postgresql://…` 형식의 DATABASE_URL을 SQLAlchemy 엔진 URL로 바꾼다."""
    return make_url(url).set(drivername=DB_DRIVERNAME)


def _hide_connect_error(context: ExceptionContext) -> BaseException | None:
    """접속 실패 메시지(사용자 이름·호스트 등)가 예외·로그에 남지 않도록 일반 메시지로 바꾼다.

    `context.connection`이 없으면 풀이 새 연결을 여는 중에 난 오류(접속 실패)다.
    """
    if context.connection is None and isinstance(context.sqlalchemy_exception, OperationalError):
        return OperationalError(None, None, ConnectionError("PostgreSQL connection failed"))
    return None


def create_db_engine(settings: DatabaseSettings) -> Engine:
    """앱 수명 동안 재사용하는 SQLAlchemy 엔진(연결 풀 포함). 첫 사용 시점에 접속합니다."""
    engine = create_engine(
        sqlalchemy_url(settings.url),
        connect_args={"connect_timeout": settings.timeout},
        pool_size=settings.pool_size,
        max_overflow=0,
        pool_timeout=settings.timeout,
        pool_pre_ping=True,
        hide_parameters=True,
    )
    event.listen(engine, "handle_error", _hide_connect_error)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: 커밋 뒤에도 응답 직렬화(Pydantic)에서 ORM 객체를 읽을 수 있게 합니다.
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """요청마다 Session 하나를 제공한다. 성공한 쓰기의 commit은 호출자가 담당한다."""
    factory = request.app.state.db_session_factory
    if factory is None:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="database not configured")

    session = factory()
    try:
        yield session
    except (OperationalError, PoolTimeoutError) as exc:
        # 예외 메시지는 자격정보를 담을 수 있어 로그에도 클래스 이름만 남깁니다.
        raise AppError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=f"database error: {type(exc).__name__}"
        ) from None
    finally:
        # 남은 트랜잭션은 롤백되고 연결은 풀로 반환됩니다.
        session.close()
