from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from psycopg import OperationalError
from psycopg.pq import TransactionStatus
from psycopg_pool import PoolTimeout

from app.core.config import DatabaseSettings, get_settings
from app.main import create_app


@pytest.fixture
def configured_app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:example@localhost/career")
    pool = Mock()
    monkeypatch.setattr("app.main.create_pool", Mock(return_value=pool))
    get_settings.cache_clear()
    try:
        yield create_app(), pool
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("disconnect", [False, True])
def test_database_health_returns_connection(configured_app, disconnect):
    app, pool = configured_app
    connection = pool.getconn.return_value
    connection.info.transaction_status = (
        TransactionStatus.UNKNOWN if disconnect else TransactionStatus.INTRANS
    )
    if disconnect:
        connection.execute.side_effect = OperationalError("sensitive details")

    with TestClient(app) as client:
        response = client.get("/health/db")
        pool.open.assert_called_once()
        pool.close.assert_not_called()

    assert response.status_code == (503 if disconnect else 200)
    assert response.json() == (
        {"detail": "Database unavailable"} if disconnect else {"status": "ok"}
    )
    connection.execute.assert_called_once_with("SELECT 1")
    pool.putconn.assert_called_once_with(connection)
    assert connection.rollback.call_count == (0 if disconnect else 1)
    pool.close.assert_called_once()


def test_pool_timeout_returns_generic_error(configured_app):
    app, pool = configured_app
    pool.getconn.side_effect = PoolTimeout("sensitive details")
    with TestClient(app) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    pool.putconn.assert_not_called()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATABASE_URL", "postgresql://app:example@%xx/career"),
        ("DB_POOL_SIZE", "0"),
        ("DB_TIMEOUT_SECONDS", "sentinel-value"),
    ],
)
def test_invalid_database_settings_hide_values(monkeypatch, name, value):
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:example@localhost/career")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name) as exc:
        DatabaseSettings.from_env()
    assert "example" not in str(exc.value)
    assert "sentinel-value" not in str(exc.value)
