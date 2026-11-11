"""T102 개인 지원 기록 — 규칙 단위 시험(메모리 저장소, DB 없음)."""
import importlib.util
import typing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.schemas.job_applications import ApplicationStage, JobApplicationCreate, JobApplicationUpdate
from app.services.job_applications import (
    MAX_PER_USER, NEEDS_DATE, NO_DATE, STAGES, TRANSITIONS, ApplicationRow, JobApplicationService, NewApplication, can_move,
)
from app.services.job_postings import ListCursor
from tests.security.security_pg import ROOT

NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)           # KST 2026-11-11 12:00
TODAY = date(2026, 11, 11)
A, B, POSTING = uuid4(), uuid4(), uuid4()


def t101():
    spec = importlib.util.spec_from_file_location("t101", ROOT / "docs/applications/test_t101_application_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryRepo:
    def __init__(self):
        self.rows: dict[UUID, ApplicationRow] = {}
        self.postings = {POSTING: ("합성 공고", "합성 기업", "published", None)}

    def list(self, user_id, stages, after, limit):
        rows = [r for r in self.rows.values() if r.user_id == user_id and (not stages or r.stage in stages)]
        rows.sort(key=lambda r: (r.updated_at, r.application_id), reverse=True)
        if after:
            rows = [r for r in rows if (r.updated_at, r.application_id) < after]
        return rows[:limit]

    def get(self, user_id, application_id):
        row = self.rows.get(application_id)
        return row if row and row.user_id == user_id else None

    def create(self, new: NewApplication, max_per_user):
        if new.job_posting_id not in self.postings:
            return "posting_not_found"
        mine = [r for r in self.rows.values() if r.user_id == new.user_id]
        if any(r.job_posting_id == new.job_posting_id for r in mine):
            return "duplicate"
        if len(mine) >= max_per_user:
            return "limit"
        title, company, status, expires = self.postings[new.job_posting_id]
        row = ApplicationRow(uuid4(), new.user_id, new.job_posting_id, title, company, status, expires, new.stage,
                             new.applied_on, new.next_step_on, new.memo, 1, new.now, new.now, new.now)
        self.rows[row.application_id] = row
        return row

    def update(self, user_id, application_id, version, values):
        row = self.get(user_id, application_id)
        if row is None or row.version != version:
            return None
        self.rows[application_id] = replace(row, version=version + 1, **values)
        return self.rows[application_id]

    def delete(self, user_id, application_id):
        return self.rows.pop(application_id, None) is not None if self.get(user_id, application_id) else False


@pytest.fixture
def svc():
    return JobApplicationService(MemoryRepo(), ListCursor(b"k" * 32), clock=lambda: NOW)


def code_of(call):
    with pytest.raises(AppError) as info:
        call()
    return info.value.code


def make(svc, user=A, **kw):
    return svc.create(user, JobApplicationCreate(job_posting_id=kw.pop("posting", POSTING), **kw))


def patch(svc, app, user=A, **kw):
    return svc.update(user, app.application_id, JobApplicationUpdate(version=kw.pop("version", app.version), **kw))


def test_rules_match_the_t101_contract_table_and_proposal_enum():
    contract = t101()
    assert {k: set(v) for k, v in TRANSITIONS.items()} == contract.table_from_doc() == contract.TRANSITIONS
    assert STAGES == contract.STAGES == typing.get_args(ApplicationStage)
    assert NEEDS_DATE == contract.NEEDS_DATE and NO_DATE == contract.NO_DATE


@pytest.mark.parametrize("current", STAGES)
@pytest.mark.parametrize("target", STAGES)
def test_every_pair_of_stages(svc, current, target):
    """49쌍 — 허용이면 200, 아니면 409 CONFLICT 이고 기록은 그대로."""
    svc.repo.rows.clear()
    app = make(svc, stage=current)
    if can_move(current, target):
        moved = patch(svc, app, stage=target)
        assert moved.stage == target and moved.version == 2
        assert (moved.applied_on is None) if target in NO_DATE else True
        assert (moved.applied_on is not None) if target in NEEDS_DATE else True
    else:
        assert code_of(lambda: patch(svc, app, stage=target)) is ErrorCode.CONFLICT
        assert svc.get(A, app.application_id) == app


def test_applied_on_is_filled_kept_and_cleared(svc):
    app = make(svc)
    assert app.applied_on is None
    applied = patch(svc, app, stage="applied")
    assert applied.applied_on == TODAY                               # KST 오늘로 채움
    dated = patch(svc, applied, applied_on=date(2026, 11, 1))
    interview = patch(svc, dated, stage="interviewing", next_step_on=date(2026, 11, 20))
    assert interview.applied_on == date(2026, 11, 1)                 # 유지
    back = patch(svc, patch(svc, interview, stage="applied"), stage="preparing")
    assert back.applied_on is None                                   # 준비로 돌아가면 지움
    assert code_of(lambda: patch(svc, back, applied_on=date(2026, 11, 1))) is ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("kw", [
    dict(stage="applied", applied_on=TODAY + timedelta(days=1)),     # 미래 지원일
    dict(stage="applied", applied_on=date(1999, 12, 31)),
    dict(next_step_on=TODAY + timedelta(days=731)),
    dict(next_step_on=date(1999, 1, 1)),
    dict(stage="preparing", applied_on=TODAY),                       # 지원 전인데 지원일
])
def test_invalid_dates_are_422(svc, kw):
    assert code_of(lambda: make(svc, **kw)) is ErrorCode.VALIDATION_FAILED


def test_version_conflict_and_empty_patch(svc):
    app = make(svc)
    patch(svc, app, memo="첫 수정")
    assert code_of(lambda: patch(svc, app, memo="오래된 화면에서 수정")) is ErrorCode.CONFLICT
    assert svc.get(A, app.application_id).memo == "첫 수정"
    assert code_of(lambda: svc.update(A, app.application_id, JobApplicationUpdate(version=2))) is ErrorCode.VALIDATION_FAILED
    assert code_of(lambda: patch(svc, svc.get(A, app.application_id), stage=None)) is ErrorCode.VALIDATION_FAILED


def test_null_clears_and_missing_keeps(svc):
    app = make(svc, memo="메모", next_step_on=date(2026, 11, 20))
    kept = patch(svc, app, stage="preparing")
    assert (kept.memo, kept.next_step_on) == ("메모", date(2026, 11, 20))
    cleared = patch(svc, kept, memo=None, next_step_on=None)
    assert (cleared.memo, cleared.next_step_on) == (None, None)


def test_owner_only_duplicate_limit_and_missing_posting(svc):
    app = make(svc)
    for call in (lambda: svc.get(B, app.application_id), lambda: patch(svc, app, user=B, memo="x"),
                 lambda: svc.delete(B, app.application_id)):
        assert code_of(call) is ErrorCode.NOT_FOUND
    assert svc.list(B, None, 20, None).items == []
    assert code_of(lambda: make(svc)) is ErrorCode.CONFLICT                         # 같은 공고
    assert code_of(lambda: make(svc, posting=uuid4())) is ErrorCode.NOT_FOUND
    for _ in range(MAX_PER_USER):
        p = uuid4()
        svc.repo.postings[p] = ("p", "c", "published", None)
        make(svc, user=B, posting=p)
    p = uuid4()
    svc.repo.postings[p] = ("p", "c", "published", None)
    assert code_of(lambda: make(svc, user=B, posting=p)) is ErrorCode.CONFLICT     # 500건 상한


def test_posting_status_view(svc):
    app = make(svc)
    assert app.posting.status == "published"
    row = svc.repo.rows[app.application_id]
    svc.repo.rows[app.application_id] = replace(row, posting_expires_at=NOW - timedelta(seconds=1))
    assert svc.get(A, app.application_id).posting.status == "closed"
    svc.repo.rows[app.application_id] = replace(row, job_posting_id=None, posting_status=None)
    gone = svc.get(A, app.application_id)
    assert (gone.posting.status, gone.posting.title, gone.posting.expires_at) == ("unavailable", "합성 공고", None)


def test_flag_off_by_default_registers_no_route(monkeypatch):
    monkeypatch.delenv("JOB_APPLICATIONS_API", raising=False)
    assert Settings.from_env().job_applications_api is False
    get_settings.cache_clear()
    try:
        paths = {getattr(r, "path", "") for r in create_app().routes}
    finally:
        get_settings.cache_clear()
    assert not any("job-applications" in p for p in paths)
