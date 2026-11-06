from collections.abc import Iterator

from fastapi import HTTPException, Request
from psycopg import Connection, OperationalError
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool, PoolTimeout

from app.core.config import DatabaseSettings


class DatabaseConnection(Connection):
    @classmethod
    def connect(cls, *args, **kwargs):
        # Pool workers log connection failures, so sanitize at the driver boundary.
        try:
            return super().connect(*args, **kwargs)
        except OperationalError:
            raise OperationalError("PostgreSQL connection failed") from None


def create_pool(settings: DatabaseSettings) -> ConnectionPool:
    return ConnectionPool(
        settings.url,
        connection_class=DatabaseConnection,
        kwargs={"connect_timeout": settings.timeout},
        min_size=0,
        max_size=settings.pool_size,
        timeout=settings.timeout,
        check=ConnectionPool.check_connection,
        open=False,
    )


def get_db(request: Request) -> Iterator[Connection]:
    """Provide one connection per request. The caller commits successful writes."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        connection = pool.getconn()
        try:
            yield connection
        finally:
            try:
                if connection.info.transaction_status in (
                    TransactionStatus.INTRANS,
                    TransactionStatus.INERROR,
                ):
                    connection.rollback()
            finally:
                pool.putconn(connection)
    except (OperationalError, PoolTimeout):
        raise HTTPException(status_code=503, detail="Database unavailable") from None
