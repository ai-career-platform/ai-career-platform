"""T47 추천 피드백 API — DB 없이 도는 서비스·HTTP 테스트 (CI 기본 실행).

T45(추천 실행 API)가 머지되지 않아 추천 실행·항목은 `MemoryRecommendationFeedbackRepository.add_run()`으로 만든다.
실제 PostgreSQL 검증은 tests/test_t47_recommendation_feedback_postgres.py (T47_TEST_DATABASE_URL 지정 시).
"""

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.core.config import API_V1_PREFIX, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import issue_access_token
from app.main import create_app
from app.repositories.recommendation_feedback import AuditRecord, FeedbackRecord, SqlRecommendationFeedbackRepository
from app.routers.recommendation_feedback import get_recommendation_feedback_service
from app.schemas.recommendation_feedback import RecommendationFeedbackInput
from app.services.recommendation_feedback import AUDIT_ACTION, AUDIT_RESOURCE, RecommendationFeedbackService
from tests.conftest import TEST_SECRET, bearer, signup
from tests.fakes import MemoryAuthRepository, MemoryRecommendationFeedbackRepository, override_auth_repository

URL = f"{API_V1_PREFIX}/recommendation-feedback"
T0 = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
POST_A = uuid.UUID("2d4f6a8c-0e1b-4d3f-8a5c-7e9b1d3f5a7c")
POST_B = uuid.UUID("2d4f6a8c-0e1b-4d3f-8a5c-7e9b1d3f5a7d")
POST_C = uuid.UUID("2d4f6a8c-0e1b-4d3f-8a5c-7e9b1d3f5a7e")  # 누구에게도 추천되지 않은 공고
NOT_FOUND = {"code": "NOT_FOUND", "status": 404, "message": "요청한 정보를 찾을 수 없습니다."}
ALICE = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
BOB = uuid.UUID("00000000-0000-4000-8000-0000000000b2")


def ticking_clock(start: datetime = T0):
    counter = itertools.count()
    return lambda: start + timedelta(seconds=next(counter))


@pytest.fixture
def repo() -> MemoryRecommendationFeedbackRepository:
    return MemoryRecommendationFeedbackRepository()


@pytest.fixture
def service(repo) -> RecommendationFeedbackService:
    return RecommendationFeedbackService(repo, clock=ticking_clock())


@pytest.fixture
def client(monkeypatch, repo):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth_repo = MemoryAuthRepository()
    clock = ticking_clock()
    override_auth_repository(app, auth_repo)
    app.dependency_overrides[get_recommendation_feedback_service] = (
        lambda: RecommendationFeedbackService(repo, clock=clock))
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as c:
        yield c
    get_settings.cache_clear()


def login(client: TestClient, email: str) -> tuple[uuid.UUID, dict[str, str]]:
    token = signup(client, email=email).json()["access_token"]
    headers = bearer(token)
    user_id = uuid.UUID(client.get(f"{API_V1_PREFIX}/me", headers=headers).json()["user_id"])
    return user_id, headers


@pytest.fixture
def alice(client, repo):
    user_id, headers = login(client, "alice@example.invalid")
    run = repo.add_run(user_id, [POST_A, POST_B])
    return user_id, headers, run


@pytest.fixture
def bob(client, repo):
    user_id, headers = login(client, "bob@example.invalid")
    run = repo.add_run(user_id, [POST_A])
    return user_id, headers, run


def body(job_posting_id=POST_A, feedback="liked", run=None) -> dict:
    out = {"job_posting_id": str(job_posting_id), "feedback": feedback}
    if run is not None:
        out["recommendation_run_id"] = str(run)
    return out


# ------------------------------------------------------------------ 정상 흐름
def test_create_returns_201_contract_shape_and_appends_history(client, repo, alice):
    user_id, headers, run = alice
    r = client.post(URL, json=body(run=run), headers={**headers, "X-Request-ID": "req-t47-normal-01"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert set(data) == {"feedback_id", "job_posting_id", "feedback", "created_at"}
    assert data["job_posting_id"] == str(POST_A) and data["feedback"] == "liked"
    uuid.UUID(data["feedback_id"])
    assert datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")).tzinfo is not None
    assert str(user_id) not in r.text  # 사용자 ID는 응답에 넣지 않는다

    [row] = repo.feedback_rows()
    assert (row.user_id, row.recommendation_run_id, row.job_posting_id, row.feedback) == (user_id, run, POST_A, "liked")
    assert str(row.feedback_id) == data["feedback_id"]
    assert repo.locks == [(user_id, POST_A)]


def test_run_id_is_optional_when_posting_was_recommended_to_me(client, repo, alice):
    _, headers, _ = alice
    r = client.post(URL, json=body(POST_B, "not_interested"), headers=headers)
    assert r.status_code == 201
    [row] = repo.feedback_rows()
    assert row.recommendation_run_id is None and row.feedback == "not_interested"


def test_audit_event_written_with_ids_only(client, repo, alice):
    user_id, headers, run = alice
    r = client.post(URL, json=body(run=run), headers={**headers, "X-Request-ID": "req-t47-audit-0001"})
    [event] = repo.audit_rows()
    assert event.actor_user_id == user_id
    assert (event.action_code, event.resource_type) == (AUDIT_ACTION, AUDIT_RESOURCE)
    assert str(event.resource_id) == r.json()["feedback_id"]
    assert event.request_id == "req-t47-audit-0001" == r.headers["x-request-id"]
    # 감사 행에는 피드백 값·공고·이메일 같은 내용이 들어갈 자리가 없다 (F11 기본 컬럼만)
    assert set(event.__dataclass_fields__) == {
        "actor_user_id", "action_code", "resource_type", "resource_id", "request_id", "occurred_at"}


# ------------------------------------------------------------------ 중복·정정·취소
def test_same_value_twice_is_idempotent_no_new_history_or_audit(client, repo, alice):
    _, headers, run = alice
    first = client.post(URL, json=body(run=run), headers=headers)
    again = client.post(URL, json=body(run=run), headers=headers)
    without_run = client.post(URL, json=body(), headers=headers)
    assert first.status_code == again.status_code == without_run.status_code == 201
    assert first.json() == again.json() == without_run.json()
    assert len(repo.feedback_rows()) == 1
    assert len(repo.audit_rows()) == 1


def test_correction_appends_row_and_latest_wins(client, repo, service, alice):
    user_id, headers, run = alice
    a = client.post(URL, json=body(run=run, feedback="liked"), headers=headers).json()
    b = client.post(URL, json=body(run=run, feedback="not_interested"), headers=headers).json()
    c = client.post(URL, json=body(run=run, feedback="liked"), headers=headers).json()
    assert len({a["feedback_id"], b["feedback_id"], c["feedback_id"]}) == 3
    assert a["created_at"] < b["created_at"] < c["created_at"]
    assert [r.feedback for r in repo.feedback_rows()] == ["liked", "not_interested", "liked"]
    assert len(repo.audit_rows()) == 3
    assert service.current_feedback(user_id, [POST_A]) == {POST_A: "liked"}


def test_correction_wins_even_when_clock_goes_backwards(repo):
    """앱 시계가 뒤로 가도(인스턴스 간 어긋남·시계 조정) 정정이 현재 값이 된다 (FR-ANL-004 수용 기준 2)."""
    times = iter([T0, T0 - timedelta(minutes=5), T0 - timedelta(minutes=5), T0 - timedelta(hours=1)])
    run = repo.add_run(ALICE, [POST_A])
    service = RecommendationFeedbackService(repo, clock=lambda: next(times))
    first = service.create(ALICE, RecommendationFeedbackInput(recommendation_run_id=run, job_posting_id=POST_A,
                                                              feedback="liked"), None)
    second = service.create(ALICE, RecommendationFeedbackInput(job_posting_id=POST_A, feedback="not_interested"),
                            None)
    third = service.create(ALICE, RecommendationFeedbackInput(job_posting_id=POST_A, feedback="cleared"), None)
    assert first.created_at < second.created_at < third.created_at
    assert second.created_at == T0 + timedelta(microseconds=1)
    assert [r.feedback for r in repo.feedback_rows()] == ["liked", "not_interested", "cleared"]
    assert [a.occurred_at for a in repo.audit_rows()] == [first.created_at, second.created_at, third.created_at]
    assert service.current_feedback(ALICE, [POST_A]) == {POST_A: None}
    # 중복 판정도 최신 행(cleared)과 비교한다 → liked는 새 행
    assert service.create(ALICE, RecommendationFeedbackInput(job_posting_id=POST_A, feedback="liked"), None) \
        .feedback_id != first.feedback_id


def test_cleared_appends_row_and_current_becomes_null(client, repo, service, alice):
    user_id, headers, run = alice
    client.post(URL, json=body(run=run, feedback="not_interested"), headers=headers)
    assert service.not_interested_ids(user_id, [POST_A, POST_B]) == {POST_A}
    r = client.post(URL, json=body(run=run, feedback="cleared"), headers=headers)
    assert r.status_code == 201 and r.json()["feedback"] == "cleared"
    assert [row.feedback for row in repo.feedback_rows()] == ["not_interested", "cleared"]
    assert service.current_feedback(user_id, [POST_A]) == {POST_A: None}
    assert service.not_interested_ids(user_id, [POST_A, POST_B]) == set()
    # 취소를 한 번 더 보내도 이력은 늘지 않는다
    assert client.post(URL, json=body(run=run, feedback="cleared"), headers=headers).json() == r.json()
    assert len(repo.feedback_rows()) == 2


def test_cleared_without_previous_feedback_records_one_row(client, repo, alice):
    _, headers, run = alice
    r = client.post(URL, json=body(run=run, feedback="cleared"), headers=headers)
    assert r.status_code == 201
    assert [row.feedback for row in repo.feedback_rows()] == ["cleared"]


def test_feedback_from_a_later_run_continues_same_posting_history(client, repo, alice):
    user_id, headers, run1 = alice
    run2 = repo.add_run(user_id, [POST_A])
    client.post(URL, json=body(run=run1, feedback="liked"), headers=headers)
    client.post(URL, json=body(run=run2, feedback="not_interested"), headers=headers)
    rows = repo.feedback_rows()
    assert [(r.recommendation_run_id, r.feedback) for r in rows] == [(run1, "liked"), (run2, "not_interested")]


# ------------------------------------------------------------------ 소유권 (404, 존재 숨김)
def test_other_users_run_is_404_and_writes_nothing(client, repo, alice, bob):
    _, alice_headers, _ = alice
    _, _, bob_run = bob
    r = client.post(URL, json=body(POST_A, run=bob_run), headers=alice_headers)
    assert r.status_code == 404
    assert r.json() == NOT_FOUND
    assert repo.feedback_rows() == [] and repo.audit_rows() == []


@pytest.mark.parametrize("case", ["unrecommended_posting", "posting_not_in_given_run", "unknown_run", "unknown_posting"])
def test_not_my_recommendation_is_indistinguishable_404(client, repo, alice, case):
    user_id, headers, run = alice
    other_run = repo.add_run(user_id, [POST_B])
    payload = {
        "unrecommended_posting": body(POST_C),
        "posting_not_in_given_run": body(POST_A, run=other_run),
        "unknown_run": body(POST_A, run=uuid.uuid4()),
        "unknown_posting": body(uuid.uuid4(), run=run),
    }[case]
    r = client.post(URL, json=payload, headers=headers)
    assert r.status_code == 404
    assert r.json() == NOT_FOUND
    assert repo.feedback_rows() == []


def test_per_user_history_is_isolated(client, repo, service, alice, bob):
    alice_id, alice_headers, alice_run = alice
    bob_id, bob_headers, bob_run = bob
    client.post(URL, json=body(POST_A, "not_interested", alice_run), headers=alice_headers)
    # Bob의 중복 판정은 Bob 이력만 본다: Alice와 같은 값이어도 Bob 첫 기록은 새 행
    r = client.post(URL, json=body(POST_A, "not_interested", bob_run), headers=bob_headers)
    assert r.status_code == 201
    client.post(URL, json=body(POST_A, "liked", bob_run), headers=bob_headers)
    assert service.current_feedback(alice_id, [POST_A]) == {POST_A: "not_interested"}
    assert service.current_feedback(bob_id, [POST_A]) == {POST_A: "liked"}
    assert [(row.user_id, row.feedback) for row in repo.feedback_rows()] == [
        (alice_id, "not_interested"), (bob_id, "not_interested"), (bob_id, "liked")]


# ------------------------------------------------------------------ 인증 401
def test_unauthenticated_is_401_before_touching_feedback(client, repo, alice):
    _, _, run = alice
    expired = issue_access_token(TEST_SECRET, uuid.uuid4(), uuid.uuid4(), [], 60, now=T0 - timedelta(days=1))
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"},
                    {"Authorization": f"Bearer {expired}"}):
        r = client.post(URL, json=body(run=run), headers=headers)
        assert r.status_code == 401, headers
        assert r.json()["code"] in {"UNAUTHENTICATED", "TOKEN_EXPIRED"}
        assert r.headers["www-authenticate"] == "Bearer"
    assert repo.feedback_rows() == [] and repo.locks == []


def test_logged_out_session_is_401(client, repo, alice):
    _, headers, run = alice
    assert client.post(f"{API_V1_PREFIX}/auth/logout", headers=headers).status_code == 204
    r = client.post(URL, json=body(run=run), headers=headers)
    assert r.status_code == 401
    assert repo.feedback_rows() == []


# ------------------------------------------------------------------ 입력 검증 422
@pytest.mark.parametrize("payload", [
    {"job_posting_id": str(POST_A), "feedback": "liked", "user_id": str(BOB)},  # 알 수 없는 필드 (user_id 주입 시도)
    {"job_posting_id": str(POST_A), "feedback": "LIKED"},
    {"job_posting_id": str(POST_A), "feedback": "dislike"},
    {"job_posting_id": str(POST_A), "feedback": ""},
    {"job_posting_id": str(POST_A), "feedback": None},
    {"job_posting_id": str(POST_A), "feedback": 1},
    {"job_posting_id": "not-a-uuid", "feedback": "liked"},
    {"job_posting_id": str(POST_A), "feedback": "liked", "recommendation_run_id": "123"},
    {"job_posting_id": str(POST_A), "feedback": "liked", "recommendation_run_id": None},
    {"job_posting_id": None, "feedback": "liked"},
    {"feedback": "liked"},
    {"job_posting_id": str(POST_A)},
    {},
    [],
    "liked",
])
def test_invalid_input_is_422_without_details(client, repo, alice, payload):
    _, headers, _ = alice
    r = client.post(URL, json=payload, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json() == {"code": "VALIDATION_FAILED", "status": 422, "message": "입력값을 확인해 주세요."}
    assert repo.feedback_rows() == []


def test_malformed_json_is_400(client, alice):
    _, headers, _ = alice
    r = client.post(URL, content=b'{"job_posting_id": ', headers={**headers, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["code"] == "MALFORMED_JSON"


def test_wrong_method_is_405(client, alice):
    _, headers, _ = alice
    r = client.get(URL, headers=headers)
    assert r.status_code == 405 and "POST" in r.headers["allow"]


# ------------------------------------------------------------------ 서비스 단위
def test_failure_after_insert_rolls_back(repo):
    user = uuid.uuid4()
    repo.add_run(user, [POST_A])

    def broken_audit(event):
        raise RuntimeError("audit write failed")

    repo.record_audit = broken_audit
    service = RecommendationFeedbackService(repo, clock=ticking_clock())
    with pytest.raises(RuntimeError):
        service.create(user, RecommendationFeedbackInput(job_posting_id=POST_A, feedback="liked"), None)
    assert repo.feedback_rows() == [] and repo.commits == 0 and repo.rollbacks >= 1


@pytest.mark.parametrize("stage", ["lock_feedback", "insert_feedback", "commit"])
def test_database_error_rolls_back_and_maps_to_503(repo, stage):
    from sqlalchemy.exc import OperationalError
    user = uuid.uuid4()
    repo.add_run(user, [POST_A])

    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("synthetic db outage"))

    setattr(repo, stage, broken)
    service = RecommendationFeedbackService(repo, clock=ticking_clock())
    with pytest.raises(AppError) as err:
        service.create(user, RecommendationFeedbackInput(job_posting_id=POST_A, feedback="liked"), None)
    assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE and err.value.status == 503
    assert "synthetic" not in str(err.value)
    assert repo.feedback_rows() == [] and repo.audit_rows() == [] and repo.rollbacks >= 1


def test_database_outage_is_503_over_http(client, repo, alice):
    from sqlalchemy.exc import OperationalError
    _, headers, run_id = alice

    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("synthetic db outage"))

    repo.insert_feedback = broken
    r = client.post(URL, json=body(run=run_id), headers=headers)
    assert r.status_code == 503 and r.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "synthetic" not in r.text and repo.feedback_rows() == []


def test_not_found_rolls_back_and_raises_app_error(repo, service):
    with pytest.raises(AppError) as err:
        service.create(uuid.uuid4(), RecommendationFeedbackInput(job_posting_id=POST_A, feedback="liked"), None)
    assert err.value.code == ErrorCode.NOT_FOUND
    assert repo.commits == 0 and repo.rollbacks == 1


def test_current_feedback_for_t45_items(repo, service):
    user = uuid.uuid4()
    run = repo.add_run(user, [POST_A, POST_B, POST_C])
    service.create(user, RecommendationFeedbackInput(recommendation_run_id=run, job_posting_id=POST_A,
                                                     feedback="liked"), None)
    service.create(user, RecommendationFeedbackInput(job_posting_id=POST_B, feedback="not_interested"), None)
    current = service.current_feedback(user, [POST_A, POST_B, POST_C, POST_A])
    assert current == {POST_A: "liked", POST_B: "not_interested", POST_C: None}
    assert list(current) == [POST_A, POST_B, POST_C]  # 입력 순서 유지, 중복 제거
    assert service.current_feedback(uuid.uuid4(), [POST_A]) == {POST_A: None}  # 다른 사용자 이력은 안 보임
    assert service.current_feedback(user, []) == {}


# ------------------------------------------------------------------ 계약
def test_generated_openapi_matches_contract(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"][URL]["post"]
    assert op["operationId"] == "createRecommendationFeedback"
    assert op["tags"] == ["insights"]
    assert {"201", "401", "404", "422"} <= set(op["responses"])
    assert "200" not in op["responses"]
    schemas = spec["components"]["schemas"]
    assert set(schemas["RecommendationFeedbackInput"]["properties"]) == {
        "recommendation_run_id", "job_posting_id", "feedback"}
    assert set(schemas["RecommendationFeedbackInput"]["required"]) == {"job_posting_id", "feedback"}
    assert schemas["RecommendationFeedbackInput"]["additionalProperties"] is False
    assert set(schemas["RecommendationFeedback"]["required"]) == {
        "feedback_id", "job_posting_id", "feedback", "created_at"}


def test_openapi_yaml_contract_is_what_we_implement():
    spec = yaml.safe_load((Path(__file__).parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    op = spec["paths"]["/recommendation-feedback"]["post"]
    assert op["operationId"] == "createRecommendationFeedback"
    assert set(op["responses"]) == {"201", "401", "404", "422"}
    schemas = spec["components"]["schemas"]
    inp, out = schemas["RecommendationFeedbackInput"], schemas["RecommendationFeedback"]
    assert inp["additionalProperties"] is False and out["additionalProperties"] is False
    assert set(inp["properties"]) == {"recommendation_run_id", "job_posting_id", "feedback"}
    assert inp["properties"]["feedback"]["enum"] == ["liked", "not_interested", "cleared"]
    assert set(out["required"]) == {"feedback_id", "job_posting_id", "feedback", "created_at"}
    # T45 RecommendationItem.feedback 는 cleared 를 null 로 보여 준다 (current_feedback 과 같은 규칙)
    assert schemas["RecommendationItem"]["properties"]["feedback"]["enum"] == ["liked", "not_interested", None]


# ------------------------------------------------------------------ SQL 형태 (DB 없이 PostgreSQL 방언으로 컴파일)
class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list = []

    def execute(self, stmt):
        self.statements.append(stmt)

        class _Result:
            def scalar(self):
                return False

            def __iter__(self):
                return iter([])

        return _Result()


def _sql(stmt) -> str:
    return " ".join(str(stmt.compile(dialect=postgresql.dialect())).split())


def test_sql_repository_statements_target_d05_d07_and_f11():
    session = _RecordingSession()
    sql_repo = SqlRecommendationFeedbackRepository(session)  # type: ignore[arg-type]
    user, run = uuid.uuid4(), uuid.uuid4()
    sql_repo.lock_feedback(user, POST_A)
    assert sql_repo.is_recommended_to(user, POST_A, None) is False
    sql_repo.is_recommended_to(user, POST_A, run)
    assert sql_repo.latest_feedback(user, []) == {}  # 빈 목록은 쿼리하지 않는다
    sql_repo.latest_feedback(user, [POST_A])
    sql_repo.insert_feedback(FeedbackRecord(uuid.uuid4(), user, None, POST_A, "liked", T0))
    sql_repo.record_audit(AuditRecord(user, AUDIT_ACTION, AUDIT_RESOURCE, uuid.uuid4(), "req-t47-sql-0001", T0))
    lock, owned_any, owned_run, latest, ins, audit = (_sql(s) for s in session.statements)

    assert "pg_advisory_xact_lock(hashtextextended(" in lock
    for owned in (owned_any, owned_run):
        assert "FROM career.recommendation_items JOIN career.recommendation_runs" in owned
        assert "career.recommendation_runs.user_id =" in owned
    assert "career.recommendation_items.recommendation_run_id =" not in owned_any
    assert "career.recommendation_items.recommendation_run_id =" in owned_run
    assert latest.startswith("SELECT DISTINCT ON (career.recommendation_feedback.job_posting_id)")
    assert "WHERE career.recommendation_feedback.user_id =" in latest
    assert latest.endswith(
        "ORDER BY career.recommendation_feedback.job_posting_id, career.recommendation_feedback.created_at DESC, "
        "career.recommendation_feedback.feedback_id DESC")
    assert ins.startswith("INSERT INTO career.recommendation_feedback (feedback_id, user_id, recommendation_run_id, "
                          "job_posting_id, feedback, created_at)")
    assert audit.startswith("INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, "
                            "resource_id, request_id, occurred_at)")


# ------------------------------------------------------------------ T45 연동 (DB 없음)
def test_t45_repository_shares_t47_tables_and_latest_feedback_rule():
    from app.repositories import recommendation_feedback as t47_repo
    from app.repositories import recommendation_runs as t45_repo
    from app.repositories import recommendation_tables as tables

    # 소유권 조회는 T45가 쓰는 같은 테이블 정의를 쓴다 (별도 중복 정의 없음).
    assert t45_repo.runs is tables.runs and t45_repo.items is tables.items
    assert t47_repo.recommendation_runs is tables.runs and t47_repo.recommendation_items is tables.items
    assert t47_repo.recommendation_feedback is tables.feedback
    # T45 항목 feedback·not_interested 제외는 T47의 최신 피드백 함수를 그대로 쓴다.
    assert t45_repo.latest_feedback_records is t47_repo.latest_feedback_records
    assert t45_repo.current_feedback_values is t47_repo.current_feedback_values


def test_current_feedback_values_maps_cleared_and_missing_to_null():
    from app.repositories.recommendation_feedback import current_feedback_values

    def rec(post, value, seconds):
        return FeedbackRecord(uuid.uuid4(), ALICE, None, post, value, T0 + timedelta(seconds=seconds))

    latest = {POST_A: rec(POST_A, "liked", 1), POST_B: rec(POST_B, "cleared", 2)}
    assert current_feedback_values(latest) == {POST_A: "liked", POST_B: None}
    assert current_feedback_values(latest, [POST_C, POST_A, POST_C]) == {POST_C: None, POST_A: "liked"}
    assert current_feedback_values({}) == {}


def test_t45_latest_feedback_sql_is_single_distinct_on_query():
    from app.repositories.recommendation_feedback import latest_feedback_records

    session = _RecordingSession()
    assert latest_feedback_records(session, ALICE, []) == {}  # type: ignore[arg-type]
    assert session.statements == []
    latest_feedback_records(session, ALICE, [POST_A, POST_B, POST_A])  # type: ignore[arg-type]
    (stmt,) = session.statements
    sql = _sql(stmt)
    assert sql.startswith("SELECT DISTINCT ON (career.recommendation_feedback.job_posting_id)")
    assert "career.recommendation_feedback.user_id =" in sql
    assert "career.recommendation_feedback.job_posting_id IN (" in sql
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert [POST_A, POST_B] in params.values()  # 중복 공고 ID는 한 번만 묻는다
