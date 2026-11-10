"""T72 actual PostgreSQL tests, reusing the guarded T16 disposable DB fixture (0001 schema, synthetic users A/B).

Opt-in only: T16_ISOLATED_DB_TEST=YES and T16_TEST_ADMIN_URL pointing to a loopback t16_profile_test database.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from psycopg import sql
from sqlalchemy import event as sa_event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rate_limit import AttemptLimiter
from app.repositories.behavior_events import SqlBehaviorEventRepository
from app.repositories.privacy import SqlPrivacyRepository
from app.schemas.behavior_events import BehaviorEventInput, metadata_size
from app.schemas.privacy import OptionalConsentInput
from app.services.behavior_events import BehaviorEventService, BehaviorEventSettings, storage_event_id
from app.services.privacy import PrivacyService
from tests.test_profile_postgres import A, B, pg_app  # noqa: F401  (fixture)

PATH = "/api/v1/me/behavior-events"
ENABLED = BehaviorEventSettings(enabled=True)


@pytest.fixture
def behavior_pg(pg_app):  # noqa: F811
    client, engine, admin, headers = pg_app
    admin.execute("INSERT INTO career.consent_policies(policy_code,version,is_required,content_url,effective_at) "
                  "VALUES('behavior_tracking','v1',false,'https://example.invalid/bt',%s)",
                  (datetime.now(UTC) - timedelta(days=1),))
    # 앱 역할은 T31 fixture에서 SELECT/INSERT/UPDATE만 받는다. 철회 삭제에 필요한 DELETE만 이 표에 추가.
    admin.execute(sql.SQL("GRANT DELETE ON career.behavior_events TO {}").format(sql.Identifier(engine.url.username)))
    client.app.state.behavior_event_settings = ENABLED
    return client, engine, admin, headers


def body(**overrides):
    data = {"event_id": str(uuid4()), "event_code": "posting.view",
            "event_at": datetime.now(UTC).isoformat(), "metadata": {"job_posting_id": "jp_1", "list_position": 2}}
    data.update(overrides)
    return data


def consent(granted, user=A, engine=None, client=None, headers=None):
    payload = {"policy_code": "behavior_tracking", "policy_version": "v1", "granted": granted}
    if client is not None:
        r = client.post("/api/v1/me/consents", headers=headers, json=payload)
        assert r.status_code == 201
        return
    with Session(engine) as db:
        PrivacyService(SqlPrivacyRepository(db)).record_consent(user, OptionalConsentInput(**payload))


def service(db, limiter=None):
    return BehaviorEventService(SqlBehaviorEventRepository(db), ENABLED, limiter or AttemptLimiter())


def count(admin, user=A):
    return admin.execute("SELECT count(*) FROM career.behavior_events WHERE user_id=%s", (user,)).fetchone()[0]


def test_actual_consent_gate_dedup_and_stored_row(behavior_pg):
    client, _, admin, h = behavior_pg
    blocked = client.post(PATH, headers=h, json=body())
    assert blocked.status_code == 200 and blocked.json()["status"] == "blocked_no_consent" and count(admin) == 0
    consent(True, client=client, headers=h)
    payload = body()
    first = client.post(PATH, headers=h, json=payload)
    again = client.post(PATH, headers=h, json=payload)
    assert (first.status_code, again.status_code) == (201, 200) and again.json()["status"] == "duplicate"
    row = admin.execute("SELECT event_id,user_id,event_code,metadata,octet_length(metadata::text) "
                        "FROM career.behavior_events").fetchall()
    assert len(row) == 1
    event_id, user_id, code, metadata, size = row[0]
    assert event_id == storage_event_id(A, UUID(payload["event_id"]))
    assert (user_id, code, metadata) == (A, "posting.view", {"job_posting_id": "jp_1", "list_position": 2})
    assert size == metadata_size(metadata)


def test_actual_personalization_and_invalid_payload_store_nothing(behavior_pg):
    client, _, admin, h = behavior_pg
    consent(True, client=client, headers=h)
    r = client.post(PATH, headers=h, json=body(event_code="recommendation.click",
                                               metadata={"recommendation_id": "r1", "rank": 1}))
    assert r.json()["status"] == "blocked_policy_pending"
    assert client.post(PATH, headers=h, json=body(metadata={"job_posting_id": "free text"})).status_code == 422
    assert client.post(PATH, headers=h, json=body(
        event_at=(datetime.now(UTC) + timedelta(minutes=6)).isoformat())).status_code == 422
    assert count(admin) == 0


def test_actual_withdrawal_erases_only_own_tracking_events_and_blocks_replay(behavior_pg):
    client, engine, admin, h = behavior_pg
    consent(True, client=client, headers=h)
    consent(True, user=B, engine=engine)
    old = body()  # 첫 동의 이후에 일어난 이벤트
    assert client.post(PATH, headers=h, json=old).status_code == 201
    with Session(engine) as db:
        assert service(db).record(B, BehaviorEventInput.model_validate(body())).status == "recorded"
    assert (count(admin), count(admin, B)) == (1, 1)

    consent(False, client=client, headers=h)                 # 철회: 같은 트랜잭션에서 삭제
    assert (count(admin), count(admin, B)) == (0, 1)
    assert client.post(PATH, headers=h, json=body()).json()["status"] == "blocked_no_consent"

    time.sleep(0.05)
    consent(True, client=client, headers=h)                  # 재동의 후 예전 이벤트 재전송 → 복원 안 됨
    assert client.post(PATH, headers=h, json=old).json()["status"] == "blocked_no_consent"
    assert count(admin) == 0
    assert client.post(PATH, headers=h, json=body()).status_code == 201
    assert count(admin) == 1


def test_actual_withdrawal_waits_for_inflight_collection_and_leaves_zero(behavior_pg):
    """수집이 동의를 확인한 뒤 INSERT 직전에 멈춰 있는 동안 철회가 시작돼도, 철회는 같은 행 잠금에서
    기다렸다가 커밋된 이벤트까지 지운다 (T71 concurrency regression과 같은 순서)."""
    _, engine, admin, _ = behavior_pg
    consent(True, engine=engine)
    paused, release = threading.Event(), threading.Event()

    def pause_before_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO career.behavior_events"):
            paused.set()
            release.wait(timeout=10)

    def collect():
        with Session(engine) as db:
            return service(db).record(A, BehaviorEventInput.model_validate(body())).status

    def withdraw():
        consent(False, engine=engine)
        return "withdrawn"

    sa_event.listen(engine, "before_cursor_execute", pause_before_insert)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            collected = pool.submit(collect)
            assert paused.wait(timeout=10)
            withdrawn = pool.submit(withdraw)
            deadline = time.monotonic() + 10
            waiting = 0
            while time.monotonic() < deadline and not waiting:
                waiting = admin.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                        "AND wait_event_type='Lock'").fetchone()[0]
                time.sleep(0.05)
            assert waiting >= 1          # 철회 트랜잭션이 사용자 행 잠금을 기다리는 중
            release.set()
            assert collected.result(timeout=10) == "recorded"
            assert withdrawn.result(timeout=10) == "withdrawn"
    finally:
        release.set()
        sa_event.remove(engine, "before_cursor_execute", pause_before_insert)
    assert count(admin) == 0


@pytest.mark.parametrize("round_", range(5))
def test_actual_simultaneous_collection_and_withdrawal_never_leave_events(behavior_pg, round_):
    _, engine, admin, _ = behavior_pg
    consent(True, engine=engine)
    start = Barrier(2)

    def collect():
        with Session(engine) as db:
            start.wait(timeout=5)
            return service(db).record(A, BehaviorEventInput.model_validate(body())).status

    def withdraw():
        start.wait(timeout=5)
        consent(False, engine=engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(collect), pool.submit(withdraw)]
        status = results[0].result(timeout=10)
        results[1].result(timeout=10)
    assert status in {"recorded", "blocked_no_consent"}
    assert count(admin) == 0


def test_actual_concurrent_duplicate_event_id_is_stored_once(behavior_pg):
    _, engine, admin, _ = behavior_pg
    consent(True, engine=engine)
    payload = body()
    start = Barrier(2)

    def send(_):
        with Session(engine) as db:
            start.wait(timeout=5)
            return service(db).record(A, BehaviorEventInput.model_validate(payload)).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(send, range(2)))
    assert statuses == ["duplicate", "recorded"] and count(admin) == 1


def test_actual_storage_error_rolls_back(behavior_pg):
    _, engine, admin, _ = behavior_pg
    consent(True, engine=engine)
    with Session(engine) as db:
        def fail_commit(_):
            raise OperationalError(None, None, RuntimeError("synthetic commit failure"))
        sa_event.listen(db, "before_commit", fail_commit)
        with pytest.raises(AppError) as exc:
            service(db).record(A, BehaviorEventInput.model_validate(body()))
        assert exc.value.status == 503 and not db.in_transaction()
    assert engine.pool.checkedout() == 0 and count(admin) == 0


def test_actual_disabled_account_is_rejected(behavior_pg):
    client, engine, admin, h = behavior_pg
    consent(True, engine=engine)
    admin.execute("UPDATE career.users SET status='disabled' WHERE user_id=%s", (A,))
    assert client.post(PATH, headers=h, json=body()).status_code == 401
    with Session(engine) as db, pytest.raises(AppError) as exc:
        service(db).record(A, BehaviorEventInput.model_validate(body()))
    assert exc.value.status == 401 and count(admin) == 0
