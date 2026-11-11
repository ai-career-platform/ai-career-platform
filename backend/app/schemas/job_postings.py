"""T18 기업·채용공고 응답 스키마 (docs/api/openapi.yaml tag `catalog`).

필드 이름·필수 여부는 openapi.yaml의 CompanyRef / CompanyPage / CompanyDetail /
JobPostingSummary / JobPostingPage / JobPostingDetail / RequiredSkill과 같다.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

PostingStatus = Literal["published", "closed"]
EmploymentType = Literal["full_time", "contract", "intern", "part_time"]
PostingSort = Literal["-published_at", "expires_at"]
# T99 고급 검색(T98 제안, 기능 플래그) — app/services/job_search.py 의 표와 같은 값
RegionCode = Literal["seoul", "busan", "daegu", "incheon", "gwangju", "daejeon", "ulsan", "sejong", "gyeonggi", "gangwon",
                     "chungbuk", "chungnam", "jeonbuk", "jeonnam", "gyeongbuk", "gyeongnam", "jeju"]
PostedWithin = Literal["1d", "3d", "7d", "30d"]


class _Strict(BaseModel):
    # openapi.yaml의 additionalProperties: false와 맞춘다.
    model_config = ConfigDict(extra="forbid")


class CompanyRef(_Strict):
    company_id: UUID
    name: str


class CompanyPage(_Strict):
    items: list[CompanyRef]
    next_cursor: str | None


class CompanyDetail(_Strict):
    company_id: UUID
    name: str
    website_url: str | None
    description: str | None
    open_posting_count: int
    source: str


class JobRoleRef(_Strict):
    job_role_id: UUID
    code: str
    name: str


class SkillRef(_Strict):
    skill_id: UUID
    code: str
    name: str


class RequiredSkill(_Strict):
    skill: SkillRef
    # 공고에 수준이 없으면 직무 기본값(job_role_skills). 둘 다 없으면 null (PR 미해결 항목 참고).
    required_level: int | None
    is_required: bool


class JobPostingSummary(_Strict):
    job_posting_id: UUID
    title: str
    status: PostingStatus
    company: CompanyRef
    job_role: JobRoleRef | None
    employment_type: EmploymentType | None
    location_text: str | None
    published_at: datetime | None
    expires_at: datetime | None


class JobPostingPage(_Strict):
    items: list[JobPostingSummary]
    next_cursor: str | None


class JobPostingDetail(JobPostingSummary):
    description: str | None
    source_url: str | None
    required_skills: list[RequiredSkill]
    # 비로그인이면 null
    is_bookmarked: bool | None
