"""T99 고급 검색 규칙 단위 시험 (DB 없음). 코드의 표가 T98 계약 문서와 같은지, 기본값이 꺼져 있는지 확인합니다."""
import importlib.util
import typing

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.main import create_app
from app.schemas.job_postings import PostedWithin, RegionCode
from app.services.job_search import EMPLOYMENT_TYPES, POSTED_WITHIN, REGION_ALIASES, normalize_q, unique
from tests.security.security_pg import ROOT


def t98():
    spec = importlib.util.spec_from_file_location("t98_contract", ROOT / "docs/search/test_t98_search_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_region_table_and_enums_match_the_t98_contract():
    contract = t98()
    assert REGION_ALIASES == contract.ALIASES
    assert set(typing.get_args(RegionCode)) == set(REGION_ALIASES)
    assert set(typing.get_args(PostedWithin)) == set(POSTED_WITHIN) == set(contract.WITHIN)
    assert set(EMPLOYMENT_TYPES) == contract.EMPLOYMENT
    assert {k: v.days for k, v in POSTED_WITHIN.items()} == contract.WITHIN


@pytest.mark.parametrize(("raw", "expected"), [("  qa  ", "qa"), ("백엔드\t\t개발자", "백엔드 개발자"), ("%", "%"),
                                                ("가" * 100, "가" * 100), (None, None)])
def test_normalize_q(raw, expected):
    assert normalize_q(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\t", "가" * 101, " " + "가" * 101])
def test_normalize_q_rejects(raw):
    with pytest.raises(AppError):
        normalize_q(raw)


def test_unique_limits_count_before_dedupe_and_sorts():
    assert unique("employment_type", ["intern", "contract", "intern"]) == ("contract", "intern")
    assert unique("region", None) == ()
    with pytest.raises(AppError):
        unique("region", ["seoul"] * 6)
    assert unique("company_id", ["b"] * 10) == ("b",)


def test_flag_is_off_by_default_and_only_exact_true_enables(monkeypatch):
    monkeypatch.delenv("JOB_SEARCH_ADVANCED", raising=False)
    assert Settings.from_env().job_search_advanced is False
    for value, enabled in [("true", True), ("TRUE", True), ("1", False), ("yes", False), ("false", False)]:
        monkeypatch.setenv("JOB_SEARCH_ADVANCED", value)
        assert Settings.from_env().job_search_advanced is enabled, value


@pytest.mark.parametrize("flag", ["false", "true"])
def test_exactly_one_listing_route_is_registered(monkeypatch, flag):
    monkeypatch.setenv("JOB_SEARCH_ADVANCED", flag)
    get_settings.cache_clear()
    try:
        app = create_app()
        listing = [r for r in app.routes if getattr(r, "path", "") == "/api/v1/job-postings"]
        assert len(listing) == 1
        with TestClient(app) as client:
            params = {p["name"] for p in client.get("/openapi.json").json()["paths"]["/api/v1/job-postings"]["get"]["parameters"]}
        assert ("region" in params) is (flag == "true")
    finally:
        get_settings.cache_clear()
