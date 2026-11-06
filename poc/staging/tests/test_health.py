import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

module_path = Path(__file__).resolve().parents[1] / "backend" / "main.py"
spec = importlib.util.spec_from_file_location("staging_poc_backend", module_path)
assert spec is not None and spec.loader is not None
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
client = TestClient(backend.app)


@pytest.fixture
def db_env(monkeypatch):
    for key, value in {
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test_db",
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_password",
    }.items():
        monkeypatch.setenv(key, value)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ai-career-backend"}


def test_version(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging-poc")
    monkeypatch.setenv("APP_VERSION", "0.1.0")
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "application": "ai-career-platform",
        "environment": "staging-poc",
        "version": "0.1.0",
    }


def test_database_health_success(db_env, monkeypatch):
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(backend.psycopg, "connect", connect)

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ai-career-database"}
    cursor.execute.assert_called_once_with("SELECT 1")
    connect.assert_called_once_with(
        host="db", port="5432", dbname="test_db", user="test_user",
        password="test_password", connect_timeout=3,
    )


def test_database_health_connection_failure(db_env, monkeypatch):
    monkeypatch.setattr(
        backend.psycopg, "connect", MagicMock(side_effect=psycopg.OperationalError("test_password"))
    )
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "test_password" not in response.text


def test_database_health_unexpected_result(db_env, monkeypatch):
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (0,)
    monkeypatch.setattr(backend.psycopg, "connect", MagicMock(return_value=connection))
    response = client.get("/health/db")
    assert response.status_code == 503


def test_database_health_missing_environment(monkeypatch):
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
