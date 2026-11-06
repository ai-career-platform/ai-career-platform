from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.config import DatabaseSettings, get_settings
from app.db import create_db_engine, create_session_factory, get_db
from app.main import create_app
from app.models import Base
from app.schemas.base import ORMModel


@pytest.fixture
def configured_app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:example@localhost/career")
    engine = Mock()
    session = Mock()
    monkeypatch.setattr("app.main.create_db_engine", Mock(return_value=engine))
    monkeypatch.setattr(
        "app.main.create_session_factory", Mock(return_value=Mock(return_value=session))
    )
    get_settings.cache_clear()
    try:
        yield create_app(), engine, session
    finally:
        get_settings.cache_clear()


def test_database_health_closes_session(configured_app):
    app, engine, session = configured_app
    with TestClient(app) as client:
        response = client.get("/health/db")
        engine.dispose.assert_not_called()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert str(session.execute.call_args.args[0]) == "SELECT 1"
    session.close.assert_called_once()
    session.commit.assert_not_called()
    engine.dispose.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("sensitive details")),
        PoolTimeoutError("sensitive details"),
    ],
)
def test_connection_errors_return_generic_503(configured_app, error):
    app, _, session = configured_app
    session.execute.side_effect = error
    with TestClient(app) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["status"] == 503
    assert "sensitive" not in response.text
    session.close.assert_called_once()


def test_without_database_url_db_routes_return_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health/db").status_code == 503
            assert client.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()


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


def test_unreachable_database_error_hides_credentials():
    settings = DatabaseSettings(
        url="postgresql://appuser:SECRETPW123@127.0.0.1:1/career", pool_size=1, timeout=1
    )
    engine = create_db_engine(settings)
    try:
        with pytest.raises(OperationalError) as exc:
            engine.connect()
    finally:
        engine.dispose()
    assert "SECRETPW123" not in str(exc.value)
    assert "appuser" not in str(exc.value)


class Item(Base):
    __tablename__ = "t14_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class ItemResponse(ORMModel):
    id: int
    name: str


def test_session_rollback_and_orm_to_pydantic():
    """Session 수명주기와 ORM→Pydantic 변환 (SQLite 인메모리, 드라이버 무관 동작만 검증)."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.state.db_session_factory = create_session_factory(engine)

    @app.post("/items", response_model=ItemResponse)
    def create(name: str, session: Session = Depends(get_db)):
        item = Item(name=name)
        session.add(item)
        session.commit()
        return item

    @app.post("/items/uncommitted")
    def uncommitted(name: str, session: Session = Depends(get_db)):
        session.add(Item(name=name))
        session.flush()
        return {"ok": True}

    with TestClient(app) as client:
        created = client.post("/items", params={"name": "a"})
        client.post("/items/uncommitted", params={"name": "b"})

    assert created.json() == {"id": 1, "name": "a"}
    with Session(engine) as check:
        assert [i.name for i in check.query(Item)] == ["a"]
