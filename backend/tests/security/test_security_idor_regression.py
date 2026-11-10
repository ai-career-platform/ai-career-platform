"""T86 IDOR 회귀 — 사용자 A 의 리소스를 사용자 B 가 읽기·수정·삭제할 수 없는지.

1) 게이트(DB 없음): 경로 변수가 있는 모든 비공개 경로는 IDOR 시험 위치가 등록되어 있어야 하고, 그 시험 함수가 실제로 있어야 함
2) 실제 PostgreSQL: 기존 시험이 HTTP 수준으로 다루지 않던 career history·bookmarks 를 A/B 로 확인
"""
import ast
from pathlib import Path

import pytest

from tests.security.security_inventory import IDOR_COVERAGE, protected
from tests.security.security_pg import USER_A, USER_B, requires_pg, sec_pg  # noqa: F401  (fixture)

BACKEND = Path(__file__).resolve().parents[2]


def test_every_protected_route_with_a_path_id_has_registered_idor_coverage():
    with_ids = {r.key for r in protected() if r.has_path_param}
    assert with_ids == set(IDOR_COVERAGE), {"missing": with_ids - set(IDOR_COVERAGE),
                                            "stale": set(IDOR_COVERAGE) - with_ids}


@pytest.mark.parametrize("target", sorted({v for v in IDOR_COVERAGE.values() if v != "ADMIN_ONLY"}))
def test_registered_idor_tests_exist(target):
    file, function = target.split("::")
    tree = ast.parse((BACKEND / file).read_text(encoding="utf-8"))
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert function in names, target


def test_admin_only_entries_are_really_admin_routes():
    for (method, path), target in IDOR_COVERAGE.items():
        if target == "ADMIN_ONLY":
            assert path.startswith("/api/v1/admin/"), path


# ---------------------------------------------------------------- PostgreSQL
@requires_pg
def test_pg_career_history_is_owner_scoped(sec_pg):
    c, a, b = sec_pg.client, sec_pg.h[USER_A], sec_pg.h[USER_B]
    exp = c.post("/api/v1/me/experiences", headers=a, json={"organization": "합성 기관", "title": "Engineer"})
    assert exp.status_code == 201, exp.text
    proj = c.post("/api/v1/me/projects", headers=a, json={"title": "합성 프로젝트"})
    assert proj.status_code == 201, proj.text
    exp_id, proj_id = exp.json()["experience_id"], proj.json()["project_id"]

    assert c.get("/api/v1/me/experiences", headers=b).json() == []
    assert c.get("/api/v1/me/projects", headers=b).json() == []
    for method, path, body in [("PATCH", f"/api/v1/me/experiences/{exp_id}", {"title": "hijacked"}),
                               ("DELETE", f"/api/v1/me/experiences/{exp_id}", None),
                               ("PATCH", f"/api/v1/me/projects/{proj_id}", {"title": "hijacked"}),
                               ("DELETE", f"/api/v1/me/projects/{proj_id}", None)]:
        response = c.request(method, path, headers=b, json=body)
        assert response.status_code == 404, f"{method} {path}: {response.status_code}"
    assert sec_pg.scalar("SELECT title FROM career.user_experiences WHERE experience_id=%s", exp_id) == "Engineer"
    assert sec_pg.scalar("SELECT title FROM career.user_projects WHERE project_id=%s", proj_id) == "합성 프로젝트"
    assert sec_pg.scalar("SELECT user_id FROM career.user_experiences WHERE experience_id=%s", exp_id) == USER_A


@requires_pg
def test_pg_owner_cannot_be_chosen_by_the_client(sec_pg):
    c, a = sec_pg.client, sec_pg.h[USER_A]
    response = c.post("/api/v1/me/experiences", headers=a,
                      json={"organization": "합성", "title": "x", "user_id": str(USER_B)})
    if response.status_code == 201:
        owner = sec_pg.scalar("SELECT user_id FROM career.user_experiences WHERE experience_id=%s",
                              response.json()["experience_id"])
        assert owner == USER_A, "body user_id must be ignored"
    else:
        assert response.status_code == 422
    assert sec_pg.scalar("SELECT count(*) FROM career.user_experiences WHERE user_id=%s", USER_B) == 0
    query = c.get("/api/v1/me/experiences", headers=sec_pg.h[USER_B], params={"user_id": str(USER_A)})
    assert query.status_code in (200, 422) and (query.status_code == 422 or query.json() == [])


@requires_pg
def test_pg_bookmarks_are_owner_scoped(sec_pg):
    c, a, b = sec_pg.client, sec_pg.h[USER_A], sec_pg.h[USER_B]
    posting = sec_pg.scalar("SELECT job_posting_id FROM career.job_postings WHERE status='published' "
                            "ORDER BY job_posting_id LIMIT 1")
    assert c.put(f"/api/v1/me/bookmarks/{posting}", headers=a).status_code == 204
    assert c.get("/api/v1/me/bookmarks", headers=b).json()["items"] == []
    assert c.delete(f"/api/v1/me/bookmarks/{posting}", headers=b).status_code == 204   # 멱등, B 의 것만 대상
    assert [i["job_posting_id"] for i in c.get("/api/v1/me/bookmarks", headers=a).json()["items"]] == [str(posting)]
    assert sec_pg.scalar("SELECT count(*) FROM career.user_job_bookmarks WHERE user_id=%s", USER_A) == 1


@requires_pg
def test_pg_sessions_and_privacy_are_owner_scoped(sec_pg):
    c, a, b = sec_pg.client, sec_pg.h[USER_A], sec_pg.h[USER_B]
    a_sessions = c.get("/api/v1/me/sessions", headers=a).json()
    a_sid = a_sessions[0]["session_id"] if isinstance(a_sessions, list) else a_sessions["items"][0]["session_id"]
    assert c.delete(f"/api/v1/me/sessions/{a_sid}", headers=b).status_code == 404
    assert c.get("/api/v1/me", headers=a).status_code == 200, "A's session must survive B's attempt"
    me_b = c.get("/api/v1/me", headers=b).json()
    assert str(USER_A) not in str(me_b) and "t86-a@" not in str(me_b)
