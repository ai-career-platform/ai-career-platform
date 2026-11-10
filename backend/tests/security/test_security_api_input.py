"""T86 API 입력 보안 — SQL Injection·LIKE 와일드카드·형식 검증.

실패 시나리오 7(SQL Injection 입력이 쿼리 구조에 영향)을 실제 PostgreSQL 에서 확인합니다.
합성 문자열만 쓰고, 일회용 DB 의 모든 표 행 수가 전후 같은지 확인합니다(파괴 SQL 이 실행되지 않음).
"""
import json
import time

import pytest

from tests.security.security_pg import ADMIN, requires_pg, sec_pg  # noqa: F401  (fixture)

PAYLOADS = [
    "' OR '1'='1", "' OR 1=1 --", "'; DROP TABLE career.skills; --", "\" OR \"\"=\"",
    "' UNION SELECT email FROM career.users --", "1'; SELECT pg_sleep(5); --",
    "%", "_", "\\", "%' OR 'a'='a", "백엔드' OR '1'='1",
]
SEARCH = ["/api/v1/job-roles", "/api/v1/skills", "/api/v1/companies", "/api/v1/job-postings"]


def literal_match(item: dict, payload: str) -> bool:
    return payload.lower() in json.dumps(item, ensure_ascii=False).lower()


@requires_pg
@pytest.mark.parametrize("path", SEARCH)
def test_pg_search_payloads_are_treated_as_literal_text(sec_pg, path):
    before = sec_pg.counts()
    baseline = sec_pg.client.get(path, params={"q": "ja"})   # 정상 검색어(최소 길이 2 충족)
    assert baseline.status_code == 200
    for payload in PAYLOADS:
        started = time.monotonic()
        response = sec_pg.client.get(path, params={"q": payload})
        assert time.monotonic() - started < 3, f"{path} {payload!r}: query delayed (pg_sleep executed?)"
        assert response.status_code in (200, 422), f"{path} {payload!r}: {response.status_code} {response.text[:120]}"
        if response.status_code == 200:
            body = response.json()
            items = body["items"] if isinstance(body, dict) else body
            assert all(literal_match(i, payload) for i in items), f"{path} {payload!r} matched non-literal rows"
            assert "@example" not in response.text and "email" not in response.text
    assert sec_pg.counts() == before, "no table changed"


@requires_pg
def test_pg_like_wildcards_do_not_return_everything(sec_pg):
    everything = sec_pg.client.get("/api/v1/skills", params={"q": "ja"}).json()
    items = everything["items"] if isinstance(everything, dict) else everything
    assert items, "seed skills exist (Java, JavaScript)"
    for wildcard in ("%%", "__", "_%", "%_"):
        response = sec_pg.client.get("/api/v1/skills", params={"q": wildcard})
        assert response.status_code == 200, response.text
        found = response.json()["items"] if isinstance(response.json(), dict) else response.json()
        assert found == [], f"{wildcard!r} must match literally (no seed name contains it), got {len(found)} rows"


@requires_pg
def test_pg_admin_filters_reject_injection_before_sql(sec_pg):
    before = sec_pg.counts()
    window = {"from": "2026-01-01T00:00:00Z", "to": "2027-01-01T00:00:00Z"}
    for payload in PAYLOADS:
        audit = sec_pg.client.get("/api/v1/admin/audit-events", headers=sec_pg.h[ADMIN],
                                  params={**window, "action_code": payload})
        assert audit.status_code == 200 and audit.json()["items"] == [] or audit.status_code == 422, payload
        actor = sec_pg.client.get("/api/v1/admin/audit-events", headers=sec_pg.h[ADMIN],
                                  params={**window, "actor_user_id": payload})
        assert actor.status_code == 422, payload
        usage = sec_pg.client.get("/api/v1/admin/ai-usage", headers=sec_pg.h[ADMIN],
                                  params={"from": "2026-11-01", "to": "2026-11-07", "group_by": payload})
        assert usage.status_code == 422, payload
    assert sec_pg.counts() == before


@requires_pg
def test_pg_cursor_and_path_injection_is_rejected(sec_pg):
    for payload in ("' OR 1=1--", "../../etc/passwd", "%00", "eyJ' OR '1'='1"):
        assert sec_pg.client.get("/api/v1/job-postings", params={"cursor": payload}).status_code == 400, payload
        assert sec_pg.client.get("/api/v1/companies", params={"cursor": payload}).status_code == 400, payload
    for payload in ("1%20OR%201=1", "'%3B--", "..%2F..%2Fhealth"):
        response = sec_pg.client.get(f"/api/v1/job-postings/{payload}")
        assert response.status_code in (404, 422), payload
