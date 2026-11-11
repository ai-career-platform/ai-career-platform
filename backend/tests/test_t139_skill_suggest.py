"""T139 기술 자동완성·동의어 검색 API 시험.

- 서비스: T137 정규화·일치 순서, 병합·폐기, 중복 제거, 페이지, 입력 거부, 성능 (합성 분류)
- HTTP: 플래그 꺼짐 404, 켜짐 200, 422/400/429, 인증 불필요
- PostgreSQL(선택): 실제 0001 스키마 + T10 Seed 의 career.skills, 최소 권한 앱 역할, 정규화 SQL 과 Python 동일성,
  제안 인덱스 적용 가능성과 실제 사용 여부
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.routers.skill_suggest import SUGGEST_LIMIT, get_skill_suggest_service
from app.services.skill_suggest import (
    Alias, MemoryTaxonomySource, SkillSuggestService, TaxonomyEntry, normalize_term,
)
from tests.conftest import TEST_SECRET
from tests.security.security_pg import disposable_pg, requires_pg

ROOT = Path(__file__).resolve().parents[2]
KEY = b"t139-local-test-only-cursor-key!!" * 2
URL = f"{API_V1_PREFIX}/skills/suggest"


def taxonomy() -> list[TaxonomyEntry]:
    """합성 분류 (T137 mock 시험 사례와 같은 성격). 실제 운영 분류가 아님."""
    return [
        TaxonomyEntry("PYTHON", "Python", aliases=(Alias("파이썬"), Alias("py"))),
        TaxonomyEntry("JAVASCRIPT", "JavaScript", aliases=(Alias("자바스크립트"), Alias("JS"))),
        TaxonomyEntry("TYPESCRIPT", "TypeScript", aliases=(Alias("타입스크립트"), Alias("TS"))),
        TaxonomyEntry("CPP", "C++", aliases=(Alias("씨쁠쁠"),)),
        TaxonomyEntry("CSHARP", "C#", aliases=(Alias("씨샵"),)),
        TaxonomyEntry("KUBERNETES", "Kubernetes", aliases=(Alias("k8s"), Alias("쿠버네티스"))),
        TaxonomyEntry("NODEJS", "Node.js", aliases=(Alias("노드"),)),
        TaxonomyEntry("REACT", "React", aliases=(Alias("리액트"),)),
        TaxonomyEntry("REACT_NATIVE", "React Native", aliases=(Alias("리액트 네이티브"),)),
        TaxonomyEntry("SPRING_BOOT", "Spring Boot", aliases=(Alias("Spring", "ambiguous"), Alias("스프링부트"))),
        TaxonomyEntry("SPRING_FRAMEWORK", "Spring Framework", aliases=(Alias("Spring", "ambiguous"),)),
        TaxonomyEntry("REACTJS", "ReactJS", status="merged", replaced_by="REACT", aliases=(Alias("React.js"),)),
        TaxonomyEntry("JQUERY", "jQuery", status="deprecated"),
        TaxonomyEntry("REST_API", "REST API 설계"),
        TaxonomyEntry("POSTGRESQL", "PostgreSQL", aliases=(Alias("포스트그레스"), Alias("postgres"))),
    ]


@pytest.fixture
def svc():
    return SkillSuggestService(MemoryTaxonomySource(taxonomy()), cursor_key=KEY)


def codes(page):
    return [i.code for i in page.items]


# ---------------------------------------------------------------- normalization (T137 parity)
@pytest.mark.parametrize("raw,expected", [
    ("  Node . JS ", "nodejs"), ("C++", "c++"), ("C#", "c#"), ("React-Native", "reactnative"),
    ("Ｐｙｔｈｏｎ", "python"), ("REST_API/설계", "restapi설계"), ("(k8s)", "k8s"), ("[TS]", "ts"),
    ("리액트 네이티브", "리액트네이티브"), ("Objective-C", "objectivec"),
])
def test_normalize_term_matches_t137_rule(raw, expected):
    assert normalize_term(raw) == expected


# ---------------------------------------------------------------- matching
def test_code_match_is_case_and_space_insensitive(svc):
    for q in ("python", "PYTHON", " Python ", "Ｐｙｔｈｏｎ"):
        page = svc.suggest(q)
        assert page.items[0].code == "PYTHON" and page.items[0].match_type == "code"
        assert codes(page).count("PYTHON") == 1


def test_korean_and_english_aliases_map_to_standard_code(svc):
    assert (svc.suggest("파이썬").items[0].code, svc.suggest("파이썬").items[0].match_type) == ("PYTHON", "alias")
    assert svc.suggest("k8s").items[0].code == "KUBERNETES"
    assert svc.suggest("쿠버네티스").items[0].code == "KUBERNETES"
    assert svc.suggest("JS").items[0].code == "JAVASCRIPT"
    assert svc.suggest("postgres").items[0].code == "POSTGRESQL"


def test_cpp_and_csharp_stay_distinct(svc):
    assert codes(svc.suggest("c++")) == ["CPP"]
    assert codes(svc.suggest("C#")) == ["CSHARP"]


def test_ambiguous_alias_returns_every_candidate_without_choosing(svc):
    page = svc.suggest("spring")
    top = [i for i in page.items if i.match_type == "ambiguous"]
    assert {i.code for i in top} == {"SPRING_BOOT", "SPRING_FRAMEWORK"}
    assert page.items[0].match_type == "ambiguous" and page.items[1].match_type == "ambiguous"


def test_merged_code_resolves_to_live_code_and_deprecated_is_hidden(svc):
    page = svc.suggest("React.js")
    assert page.items[0].code == "REACT" and page.items[0].match_type == "alias"
    old_code = svc.suggest("REACTJS")                       # 병합된 옛 코드 철자도 별칭으로
    assert (old_code.items[0].code, old_code.items[0].match_type) == ("REACT", "alias")
    assert "REACTJS" not in codes(svc.suggest("react"))
    assert svc.suggest("jquery").items == []


def test_dedupe_keeps_best_match_and_prefix_orders_shorter_first(svc):
    page = svc.suggest("react")
    assert codes(page) == ["REACT", "REACT_NATIVE"]
    assert page.items[0].match_type == "code" and page.items[1].match_type == "prefix"


def test_korean_partial_and_prefix_while_typing(svc):
    # IME 조합 중간 상태(완성 음절)로도 앞부분 일치
    assert svc.suggest("리액").items[0].code == "REACT"
    assert svc.suggest("리액").items[0].match_type == "prefix"
    assert "REST_API" in codes(svc.suggest("설계"))           # 부분 포함
    assert svc.suggest("설계").items[0].match_type == "partial"


def test_not_found_is_empty_not_error(svc):
    page = svc.suggest("존재하지않는기술")
    assert page.items == [] and page.next_cursor is None


def test_merge_cycle_and_long_chain_are_dropped_without_hanging():
    items = [TaxonomyEntry("A", "Alpha", status="merged", replaced_by="B"),
             TaxonomyEntry("B", "Beta", status="merged", replaced_by="A"),
             *[TaxonomyEntry(f"C{i}", f"Chain{i}", status="merged", replaced_by=f"C{i + 1}") for i in range(7)],
             TaxonomyEntry("C7", "Chain7")]
    service = SkillSuggestService(MemoryTaxonomySource(items), cursor_key=KEY)
    assert service.suggest("alpha").items == [] and service.suggest("beta").items == []
    assert codes(service.suggest("chain0")) == []            # 7단계 > MAX_CHAIN
    assert codes(service.suggest("chain5")) == ["C7"]        # 2단계 → 살아 있는 코드


# ---------------------------------------------------------------- input validation
@pytest.mark.parametrize("q", ["---", " ", "._/()", "a\x00b", "x" * 61, "\t"])
def test_bad_queries_are_rejected(svc, q):
    with pytest.raises(AppError) as err:
        svc.suggest(q)
    assert err.value.code == ErrorCode.VALIDATION_FAILED


# ---------------------------------------------------------------- pagination
@pytest.mark.parametrize("limit", [1, 2, 3, 50])
def test_pagination_walks_all_results_once(limit):
    items = [TaxonomyEntry(f"SKILL_{i:03d}", f"Skill {i:03d}") for i in range(23)]
    service = SkillSuggestService(MemoryTaxonomySource(items), cursor_key=KEY)
    seen, cursor = [], None
    for _ in range(30):
        page = service.suggest("skill", limit=limit, cursor=cursor)
        seen += codes(page)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 23
    assert seen == codes(service.suggest("skill", limit=50))


def test_cursor_is_bound_to_query_signature_and_data():
    items = [TaxonomyEntry(f"SKILL_{i:03d}", f"Skill {i:03d}") for i in range(5)]
    source = MemoryTaxonomySource(items)
    service = SkillSuggestService(source, cursor_key=KEY)
    cursor = service.suggest("skill", limit=2).next_cursor
    assert service.suggest("SKILL", limit=2, cursor=cursor).items     # 같은 정규화 → 허용
    for bad in [lambda: service.suggest("ski", limit=2, cursor=cursor),
                lambda: service.suggest("skill", limit=2, cursor=cursor[:-2] + ("A" if cursor[-2] != "A" else "B") + cursor[-1]),
                lambda: SkillSuggestService(source, cursor_key=b"x" * 64).suggest("skill", cursor=cursor),
                lambda: service.suggest("skill", cursor="!!!")]:
        with pytest.raises(AppError) as err:
            bad()
        assert err.value.code == ErrorCode.INVALID_CURSOR
    source.items.append(TaxonomyEntry("SKILL_NEW", "Skill new"))      # 데이터 변경 → 다시 조회
    with pytest.raises(AppError) as err:
        service.suggest("skill", limit=2, cursor=cursor)
    assert err.value.code == ErrorCode.INVALID_CURSOR


def test_source_too_large_is_refused():
    items = [TaxonomyEntry(f"S{i}", f"S{i}") for i in range(5001)]
    with pytest.raises(AppError) as err:
        SkillSuggestService(MemoryTaxonomySource(items), cursor_key=KEY).suggest("s1")
    assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_performance_on_5000_synthetic_entries():
    items = [TaxonomyEntry(f"SKILL_{i:04d}", f"합성기술 {i:04d} Framework",
                           aliases=(Alias(f"syn{i:04d}"), Alias(f"별칭{i:04d}"))) for i in range(5000)]
    service = SkillSuggestService(MemoryTaxonomySource(items), cursor_key=KEY)
    start = time.perf_counter()
    for q in ("합성", "syn12", "별칭4999", "framework", "SKILL_0001"):
        service.suggest(q, limit=10)
    per_query = (time.perf_counter() - start) / 5
    print(f"T139_PERF per_query_ms={per_query * 1000:.1f} entries=5000")
    assert per_query < 1.0


# ---------------------------------------------------------------- HTTP
def _client(monkeypatch, enabled: bool, service=None):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("SKILL_AUTOCOMPLETE_API", "true" if enabled else "false")
    get_settings.cache_clear()
    app = create_app()
    if service is not None:
        app.dependency_overrides[get_skill_suggest_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def test_flag_off_route_absent(monkeypatch):
    client = _client(monkeypatch, False)
    assert client.get(URL, params={"q": "python"}).status_code == 404
    assert "/api/v1/skills/suggest" not in client.get("/openapi.json").json()["paths"]
    get_settings.cache_clear()


def test_flag_on_contract_and_errors(monkeypatch, svc):
    client = _client(monkeypatch, True, svc)
    r = client.get(URL, params={"q": "파이썬"}, headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "next_cursor", "alias_source"} and body["alias_source"] == "taxonomy"
    assert body["items"][0] == {"code": "PYTHON", "name": "Python", "match_type": "alias", "matched": "파이썬",
                                "skill_id": None}
    assert "status" not in body["items"][0] and "replaced_by" not in body["items"][0]
    for params in ({"q": ""}, {"q": "x" * 61}, {"q": "py", "limit": 0}, {"q": "py", "limit": 51}, {"q": "---"}):
        resp = client.get(URL, params=params)
        assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_FAILED", params
    bad = client.get(URL, params={"q": "py", "cursor": "AAAA"})
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_CURSOR"
    assert client.get(URL).status_code == 422
    get_settings.cache_clear()


def test_rate_limit_429(monkeypatch, svc):
    client = _client(monkeypatch, True, svc)
    statuses = [client.get(URL, params={"q": "py"}).status_code for _ in range(SUGGEST_LIMIT + 1)]
    assert statuses[0] == 200 and statuses[-1] == 429
    get_settings.cache_clear()


# ---------------------------------------------------------------- PostgreSQL (actual schema + T10 seed)
@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("SKILL_AUTOCOMPLETE_API", "true")
    yield from disposable_pg(monkeypatch, write_tables=(), migrations=("0001", "0002", "0003"),
                             extra_sql=("UPDATE career.skills SET is_active = false WHERE code = 'SOLIDITY'",))


@requires_pg
def test_postgres_real_skills_table_suggest(pg):
    c = pg.client
    r = c.get(URL, params={"q": "python"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alias_source"] == "none"                     # T137 별칭 표 미적용
    assert body["items"][0]["code"] == "PYTHON" and body["items"][0]["match_type"] == "code"
    assert body["items"][0]["skill_id"] == str(pg.scalar("SELECT skill_id FROM career.skills WHERE code='PYTHON'"))
    assert [i["code"] for i in c.get(URL, params={"q": "c++"}).json()["items"]] == ["CPP"]
    assert [i["code"] for i in c.get(URL, params={"q": "C#"}).json()["items"]] == ["CSHARP"]
    assert c.get(URL, params={"q": "node js"}).json()["items"][0]["code"] == "NODEJS"
    assert "REST_API" in [i["code"] for i in c.get(URL, params={"q": "설계"}).json()["items"]]
    assert c.get(URL, params={"q": "solidity"}).json()["items"] == []          # 비활성 제외
    # 동의어는 실제 DB 에 없으므로 '파이썬' 은 빈 결과 (alias 표 승인 전 한계 — HOLD)
    assert c.get(URL, params={"q": "파이썬"}).json()["items"] == []
    # 페이지: 모든 활성 기술을 2개씩 끝까지 — 중복·누락 없음
    total = pg.scalar("SELECT count(*) FROM career.skills WHERE is_active AND lower(name) LIKE '%%a%%' OR "
                      "is_active AND lower(code) LIKE '%%a%%'")
    seen, cursor = [], None
    for _ in range(200):
        params = {"q": "a", "limit": 2} | ({"cursor": cursor} if cursor else {})
        page = c.get(URL, params=params).json()
        seen += [i["code"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == total
    # 앱 역할은 읽기만: 데이터 변경 없음
    assert pg.scalar("SELECT count(*) FROM career.skills WHERE NOT is_active") == 1


@requires_pg
def test_postgres_normalization_parity_and_index_proposal(pg):
    terms = ["  Node . JS ", "C++", "C#", "React-Native", "Ｐｙｔｈｏｎ", "REST_API/설계", "(k8s)", "리액트 네이티브"]
    for term in terms:
        sql_norm = pg.scalar(r"SELECT regexp_replace(lower(normalize(btrim(%s), NFKC)), '[[:space:]._/()\[\]-]+', '', 'g')",
                             term)
        assert sql_norm == normalize_term(term), term
    ddl = (ROOT / "database/proposed/T139_skill_suggest_index.sql").read_text(encoding="utf-8")
    pg.db.execute(ddl)                                         # 일회용 DB 에서만 적용 가능성 확인
    plan_default = "\n".join(r[0] for r in pg.db.execute(
        "EXPLAIN SELECT skill_id, code, name FROM career.skills WHERE is_active ORDER BY code LIMIT 5001").fetchall())
    pg.db.execute("SET enable_seqscan = off")
    plan_forced = "\n".join(r[0] for r in pg.db.execute(
        "EXPLAIN SELECT skill_id, code, name FROM career.skills WHERE is_active ORDER BY code LIMIT 5001").fetchall())
    pg.db.execute("RESET enable_seqscan")
    print("T139_PLAN_DEFAULT", plan_default.replace("\n", " | "))
    print("T139_PLAN_FORCED", plan_forced.replace("\n", " | "))
    assert "ix_skills_t139_active_code" in plan_forced
