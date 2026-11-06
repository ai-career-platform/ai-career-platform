"""`/api/v1` 서비스 API 진입점.

기능 라우터(T15 인증, T16 프로필, T17 직무·기술, T18 기업·공고 등)는
`docs/API_CONTRACT.md` 확정(T06) 후 이 라우터에 `include_router`로 추가합니다.
"""

from fastapi import APIRouter

from app.core.config import API_V1_PREFIX

api_router = APIRouter(prefix=API_V1_PREFIX)
