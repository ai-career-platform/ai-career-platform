"""T86 보안 회귀 — 실제 앱의 경로 목록(route inventory)과 검토된 예외 목록.

새 API 경로가 추가되면 아래 목록과 비교하는 테스트가 실패합니다. 목록을 고치는 것은 **보안 검토 행위**이므로
PR 리뷰에서 확인합니다(공개 경로 추가, 소유권 검사 근거 등).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

# 토큰 없이 처리되는 경로 (docs/api/openapi.yaml 에서 `security: []` 인 공개 조회·가입·로그인 + 운영 점검)
PUBLIC_ROUTES = frozenset({
    ("GET", "/health"), ("GET", "/health/db"), ("GET", "/version"),
    ("POST", "/api/v1/auth/signup"), ("POST", "/api/v1/auth/login"),
    # T93: 계약상 공개(security: []). 계정 열거 방지·요청 한도·토큰 해시는 tests/test_t93_account_recovery*.py
    ("POST", "/api/v1/auth/password-reset-requests"), ("POST", "/api/v1/auth/password-resets"),
    ("GET", "/api/v1/consent-policies"),
    ("GET", "/api/v1/companies"), ("GET", "/api/v1/companies/{company_id}"),
    ("GET", "/api/v1/job-postings"), ("GET", "/api/v1/job-postings/{job_posting_id}"),
    ("GET", "/api/v1/job-roles"), ("GET", "/api/v1/job-roles/{job_role_id}"),
    ("GET", "/api/v1/skills"),
})
# Bearer 대신 HttpOnly refresh 쿠키로 인증하는 경로 (쿠키가 없거나 틀리면 401 — PG 테스트로 확인)
COOKIE_AUTH_ROUTES = frozenset({("POST", "/api/v1/auth/refresh"), ("POST", "/api/v1/auth/logout")})

# 경로 변수가 있는 비공개 경로 → 다른 사용자 접근(IDOR)을 확인하는 테스트 위치 "파일::함수".
# admin 전용 경로는 소유자 개념이 없고 역할로 막으므로 "ADMIN_ONLY" 로 표시합니다.
IDOR_COVERAGE = {
    ("DELETE", "/api/v1/documents/{document_id}"): "tests/test_documents.py::test_ownership_and_cursors",
    ("GET", "/api/v1/documents/{document_id}"): "tests/test_documents.py::test_ownership_and_cursors",
    ("GET", "/api/v1/documents/{document_id}/file"): "tests/test_documents.py::test_ownership_and_cursors",
    ("POST", "/api/v1/documents/{document_id}/analyses"): "tests/test_document_analyses.py::test_other_owner_document_and_analysis_are_404",
    ("GET", "/api/v1/document-analyses/{analysis_id}"): "tests/test_document_analyses.py::test_other_owner_document_and_analysis_are_404",
    ("POST", "/api/v1/document-analyses/{analysis_id}/apply"): "tests/test_document_analyses.py::test_other_owner_document_and_analysis_are_404",
    ("GET", "/api/v1/matches/{match_id}"): "tests/test_matches.py::test_other_users_result_is_404",
    ("GET", "/api/v1/recommendation-runs/{recommendation_run_id}"): "tests/test_recommendation_runs.py::test_owner_isolation_and_read_only_get",
    ("DELETE", "/api/v1/me/sessions/{session_id}"): "tests/test_authz.py::test_cannot_revoke_other_users_session",
    ("PATCH", "/api/v1/me/experiences/{experience_id}"): "tests/security/test_security_idor_regression.py::test_pg_career_history_is_owner_scoped",
    ("DELETE", "/api/v1/me/experiences/{experience_id}"): "tests/security/test_security_idor_regression.py::test_pg_career_history_is_owner_scoped",
    ("PATCH", "/api/v1/me/projects/{project_id}"): "tests/security/test_security_idor_regression.py::test_pg_career_history_is_owner_scoped",
    ("DELETE", "/api/v1/me/projects/{project_id}"): "tests/security/test_security_idor_regression.py::test_pg_career_history_is_owner_scoped",
    ("PUT", "/api/v1/me/bookmarks/{job_posting_id}"): "tests/security/test_security_idor_regression.py::test_pg_bookmarks_are_owner_scoped",
    ("DELETE", "/api/v1/me/bookmarks/{job_posting_id}"): "tests/security/test_security_idor_regression.py::test_pg_bookmarks_are_owner_scoped",
    ("GET", "/api/v1/admin/crawler/runs/{run_id}/events"): "ADMIN_ONLY",
}


@dataclass(frozen=True)
class Route:
    method: str
    path: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    def url(self) -> str:
        """경로 변수에 합성 UUID 를 넣은 호출 주소."""
        return re.sub(r"{[^}]+}", lambda _: str(uuid.UUID(int=0x86)), self.path)

    @property
    def has_path_param(self) -> bool:
        return "{" in self.path

    def __str__(self) -> str:  # pytest id
        return f"{self.method} {self.path}"


def inventory(app: FastAPI | None = None) -> list[Route]:
    """앱(또는 앱 없이 등록된 라우터 전체)의 HTTP 경로. 테스트 수집 시점에는 앱을 만들지 않고 라우터에서 읽습니다."""
    if app is None:
        from app.core.config import API_V1_PREFIX
        from app.routers import api_v1, job_postings, system
        # 공고 목록은 create_app 이 기능 플래그(T99)로 legacy/advanced 중 하나를 붙임 — 경로·메서드는 같음
        listing = [APIRoute(API_V1_PREFIX + r.path, r.endpoint, methods=r.methods)
                   for r in job_postings.legacy_list_router.routes if isinstance(r, APIRoute)]
        source = list(system.router.routes) + list(api_v1.api_router.routes) + listing
    else:
        source = list(app.routes)
    routes = []
    for route in source:
        if isinstance(route, APIRoute):
            routes += [Route(m, route.path) for m in sorted(route.methods)]
    return sorted(routes, key=lambda r: (r.path, r.method))


def protected(app: FastAPI | None = None) -> list[Route]:
    return [r for r in inventory(app) if r.key not in PUBLIC_ROUTES | COOKIE_AUTH_ROUTES]


def admin_routes(app: FastAPI | None = None) -> list[Route]:
    return [r for r in inventory(app) if r.path.startswith("/api/v1/admin/")]
