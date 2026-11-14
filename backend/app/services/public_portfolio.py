"""T129 공개 포트폴리오 공유 링크 (T128 정책 PROPOSED — docs/enterprise/t128_public_profile_fields.json).

- 비공개 기본: 선택이 없으면 아무것도 공개되지 않는다. 새로 추가한 경력·프로젝트는 선택 목록에 없으므로 비공개.
- 공개하려면 선택 → 미리보기 → 동의(confirm) 순서. 선택을 바꾸면 동의가 풀린다(PP-INV-7) → 링크는 404.
- 링크 토큰: 32바이트(256비트) 임의값, 저장은 SHA-256 해시만. 원문은 만들 때 한 번만 돌려준다.
- 만료·회수·동의 철회·없는 토큰은 같은 404(PP-INV-5). 공개 화면은 현재 데이터를 그린다(삭제 즉시 반영).
- 저장소: PortfolioRepository. 실제는 SQL(migration 0007, app/repositories/public_portfolio.py), 단위 시험은 메모리.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.core.errors import AppError, ErrorCode

PUBLISHABLE_FIELDS = {"display_name", "headline", "bio", "location_text", "experience.organization",
                      "experience.title", "experience.period", "experience.description", "project.title",
                      "project.summary", "project.period", "skills", "target_roles"}
NEVER_PUBLIC = {"email", "documents", "analysis_results", "job_applications", "behavior_events",
                "consents_and_account"}
DEFAULT_TTL = timedelta(days=30)
MAX_TTL = timedelta(days=90)
MAX_ACTIVE_LINKS = 3
CONSENT_CODE = "public_profile"


@dataclass(frozen=True)
class Experience:
    experience_id: uuid.UUID
    organization: str
    title: str
    start_date: date | None
    end_date: date | None
    description: str | None


@dataclass(frozen=True)
class Project:
    project_id: uuid.UUID
    title: str
    summary: str | None
    start_date: date | None
    end_date: date | None


@dataclass(frozen=True)
class ProfileData:
    display_name: str
    headline: str | None
    bio: str | None
    location_text: str | None
    email: str
    experiences: tuple[Experience, ...] = ()
    projects: tuple[Project, ...] = ()
    skills: tuple[tuple[str, int | None], ...] = ()
    target_roles: tuple[str, ...] = ()


class ProfileSource(Protocol):
    def load(self, user_id: uuid.UUID) -> ProfileData | None: ...


@dataclass(frozen=True)
class Selection:
    fields: frozenset[str] = frozenset()
    experience_ids: frozenset[uuid.UUID] = frozenset()
    project_ids: frozenset[uuid.UUID] = frozenset()
    version: int = 1
    confirmed_version: int | None = None     # 미리보기 확인 후 동의한 선택 버전
    alias: str | None = None

    @property
    def consented(self) -> bool:
        return self.confirmed_version == self.version and bool(self.fields)


@dataclass(frozen=True)
class ShareLink:
    link_id: uuid.UUID
    user_id: uuid.UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    views: int = 0


class PortfolioRepository(Protocol):
    """선택·동의·링크 저장소. 각 쓰기 메서드는 한 번에(원자적으로) 끝난다. 모든 소유자 메서드는 user_id 로 범위를 묶는다.

    구현: MemoryPortfolioRepository(단위 시험), app.repositories.public_portfolio.SqlPortfolioRepository(migration 0007).
    """

    def get_selection(self, user_id: uuid.UUID) -> Selection: ...

    def save_selection(self, user_id: uuid.UUID, fields: frozenset[str], experience_ids: frozenset[uuid.UUID],
                       project_ids: frozenset[uuid.UUID], alias: str | None, expected_version: int,
                       now: datetime) -> Selection | str:
        """버전이 맞으면 새 선택(version+1, 동의 해제)을 저장. 실패: 'conflict' | 'not_owned'."""

    def confirm(self, user_id: uuid.UUID, version: int, policy_version: str | None,
                now: datetime) -> Selection | str:
        """미리보기 확인(동의) 기록. 실패: 'conflict' | 'empty' | 'no_policy'."""

    def withdraw(self, user_id: uuid.UUID, policy_version: str | None, now: datetime) -> None:
        """동의 철회: 선택 초기화(version+1) + 모든 링크 회수 + 철회 기록."""

    def list_links(self, user_id: uuid.UUID) -> list[ShareLink]: ...

    def add_link(self, user_id: uuid.UUID, token_hash: str, now: datetime, expires_at: datetime,
                 max_active: int) -> ShareLink | str:
        """동의된 선택 아래에서만, 활성 링크 수 검사와 함께 추가. 실패: 'not_consented' | 'limit'."""

    def revoke_link(self, user_id: uuid.UUID, link_id: uuid.UUID, now: datetime) -> bool:
        """본인 링크면 회수(이미 회수됐으면 그대로) 후 True, 없거나 남의 링크면 False."""

    def open_link(self, token_hash: str, now: datetime) -> tuple[ShareLink, Selection] | None:
        """유효·미회수·미만료 링크 + 동의된 선택이면 열람 수를 늘리고 돌려준다. 그 밖은 None."""


@dataclass
class MemoryPortfolioRepository:
    selections: dict[uuid.UUID, Selection] = field(default_factory=dict)
    links: dict[uuid.UUID, ShareLink] = field(default_factory=dict)
    consents: list[dict] = field(default_factory=list)       # user_consents 와 같은 모양(granted 이력)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    default_policy_version: str = "proposal-1"

    def delete_user(self, user_id: uuid.UUID) -> None:
        """계정 삭제(CASCADE) 흉내 — 선택·링크 삭제."""
        with self.lock:
            self.selections.pop(user_id, None)
            for link_id in [k for k, v in self.links.items() if v.user_id == user_id]:
                del self.links[link_id]

    def get_selection(self, user_id: uuid.UUID) -> Selection:
        return self.selections.get(user_id, Selection())

    def save_selection(self, user_id, fields, experience_ids, project_ids, alias, expected_version, now):
        with self.lock:
            current = self.get_selection(user_id)
            if current.version != expected_version:
                return "conflict"
            updated = Selection(fields, experience_ids, project_ids, version=current.version + 1,
                                confirmed_version=None, alias=alias)
            self.selections[user_id] = updated      # 선택이 바뀌면 동의가 풀림 → 기존 링크 404
            return updated

    def confirm(self, user_id, version, policy_version, now):
        with self.lock:
            current = self.get_selection(user_id)
            if current.version != version:
                return "conflict"
            if not current.fields:
                return "empty"
            confirmed = replace(current, confirmed_version=current.version)
            self.selections[user_id] = confirmed
            self.consents.append({"user_id": user_id, "policy_code": CONSENT_CODE,
                                  "policy_version": policy_version or self.default_policy_version, "granted": True,
                                  "selection_version": current.version, "recorded_at": now})
            return confirmed

    def withdraw(self, user_id, policy_version, now):
        with self.lock:
            current = self.get_selection(user_id)
            self.selections[user_id] = Selection(version=current.version + 1)
            for link in list(self.links.values()):
                if link.user_id == user_id and link.revoked_at is None:
                    self.links[link.link_id] = replace(link, revoked_at=now)
            self.consents.append({"user_id": user_id, "policy_code": CONSENT_CODE,
                                  "policy_version": policy_version or self.default_policy_version, "granted": False,
                                  "selection_version": current.version, "recorded_at": now})

    def list_links(self, user_id):
        return sorted((l for l in self.links.values() if l.user_id == user_id), key=lambda l: l.created_at,
                      reverse=True)

    def add_link(self, user_id, token_hash, now, expires_at, max_active):
        with self.lock:
            if not self.get_selection(user_id).consented:
                return "not_consented"
            active = [l for l in self.list_links(user_id) if l.revoked_at is None and l.expires_at > now]
            if len(active) >= max_active:
                return "limit"
            link = ShareLink(uuid.uuid4(), user_id, token_hash, now, expires_at)
            self.links[link.link_id] = link
            return link

    def revoke_link(self, user_id, link_id, now):
        with self.lock:
            link = self.links.get(link_id)
            if link is None or link.user_id != user_id:
                return False
            if link.revoked_at is None:
                self.links[link_id] = replace(link, revoked_at=now)
            return True

    def open_link(self, token_hash, now):
        with self.lock:
            link = next((l for l in self.links.values() if secrets.compare_digest(l.token_hash, token_hash)), None)
            if link is None or link.revoked_at is not None or link.expires_at <= now:
                return None
            selection = self.get_selection(link.user_id)
            if not selection.consented:
                return None
            link = replace(link, views=link.views + 1)
            self.links[link.link_id] = link
            return link, selection


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _month(value: date | None) -> str | None:
    return value.strftime("%Y-%m") if value else None


class PublicPortfolioService:
    def __init__(self, repo: PortfolioRepository, profiles: ProfileSource,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
                 policy_version: str | None = "proposal-1"):
        """policy_version=None 이면 저장소가 현재 시행 중인 `public_profile` 약관 버전을 찾는다(SQL: consent_policies)."""
        self.repo, self.profiles, self.clock, self.token_factory = repo, profiles, clock, token_factory
        self.policy_version = policy_version

    # ------------------------------------------------------------ 소유자 설정
    def selection(self, user_id: uuid.UUID) -> Selection:
        return self.repo.get_selection(user_id)

    def update_selection(self, user_id: uuid.UUID, fields: set[str], experience_ids: set[uuid.UUID],
                         project_ids: set[uuid.UUID], alias: str | None, version: int) -> Selection:
        forbidden = fields & NEVER_PUBLIC
        unknown = fields - PUBLISHABLE_FIELDS - NEVER_PUBLIC
        if forbidden or unknown:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"not publishable: {sorted(forbidden | unknown)}")
        profile = self.profiles.load(user_id)
        if profile is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="profile missing")
        own_exp = {e.experience_id for e in profile.experiences}
        own_proj = {p.project_id for p in profile.projects}
        if not experience_ids <= own_exp or not project_ids <= own_proj:
            # 남의 경력·프로젝트 ID 는 존재를 숨긴다
            raise AppError(ErrorCode.NOT_FOUND, log_detail="selected item not owned")
        result = self.repo.save_selection(user_id, frozenset(fields), frozenset(experience_ids),
                                          frozenset(project_ids), (alias or "").strip() or None, version, self.clock())
        if result == "conflict":
            raise AppError(ErrorCode.CONFLICT, log_detail="selection version mismatch")
        if result == "not_owned":        # 동시에 지워진 항목 등 — 존재를 숨긴다
            raise AppError(ErrorCode.NOT_FOUND, log_detail="selected item not owned")
        return result

    def preview(self, user_id: uuid.UUID) -> dict:
        profile = self.profiles.load(user_id)
        if profile is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="profile missing")
        return self._render(profile, self.selection(user_id))

    def confirm(self, user_id: uuid.UUID, version: int) -> Selection:
        result = self.repo.confirm(user_id, version, self.policy_version, self.clock())
        if result == "conflict":
            raise AppError(ErrorCode.CONFLICT, log_detail="preview is stale")
        if result == "empty":
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="nothing selected")
        if result == "no_policy":        # 약관(consent_policies 'public_profile') 미등록 — 공개하지 않음
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="public_profile consent policy not provisioned")
        return result

    def withdraw(self, user_id: uuid.UUID) -> None:
        """동의 철회: 모든 링크 즉시 무효 + 선택 초기화(비공개)."""
        self.repo.withdraw(user_id, self.policy_version, self.clock())

    def links(self, user_id: uuid.UUID) -> list[ShareLink]:
        return self.repo.list_links(user_id)

    def create_link(self, user_id: uuid.UUID, ttl: timedelta = DEFAULT_TTL) -> tuple[ShareLink, str]:
        if not timedelta(0) < ttl <= MAX_TTL:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="ttl out of range")
        now, token = self.clock(), self.token_factory()
        result = self.repo.add_link(user_id, _hash(token), now, now + ttl, MAX_ACTIVE_LINKS)
        if result == "not_consented":
            raise AppError(ErrorCode.CONFLICT, log_detail="confirm the preview before sharing")
        if result == "limit":
            raise AppError(ErrorCode.CONFLICT, log_detail="active link limit")
        return result, token

    def revoke_link(self, user_id: uuid.UUID, link_id: uuid.UUID) -> None:
        if not self.repo.revoke_link(user_id, link_id, self.clock()):
            raise AppError(ErrorCode.NOT_FOUND, log_detail="link missing or not owned")

    # ------------------------------------------------------------ 공개 조회(비로그인 가능)
    def view(self, token: str) -> dict:
        hidden = AppError(ErrorCode.NOT_FOUND, log_detail="public link rejected")
        opened = self.repo.open_link(_hash(token), self.clock())
        if opened is None:
            raise hidden
        link, selection = opened
        profile = self.profiles.load(link.user_id)
        if profile is None:
            raise hidden
        rendered = self._render(profile, selection)
        rendered["shared_until"] = link.expires_at.isoformat()
        return rendered

    # ------------------------------------------------------------ 렌더링(현재 데이터, 선택한 것만)
    @staticmethod
    def _render(profile: ProfileData, sel: Selection) -> dict:
        f = sel.fields
        out: dict = {}
        if "display_name" in f:
            out["display_name"] = sel.alias or profile.display_name
        for key in ("headline", "bio", "location_text"):
            if key in f and getattr(profile, key):
                out[key] = getattr(profile, key)
        exp_fields = {k.split(".", 1)[1] for k in f if k.startswith("experience.")}
        if exp_fields:
            items = []
            for e in profile.experiences:
                if e.experience_id not in sel.experience_ids:
                    continue
                item = {}
                if "organization" in exp_fields:
                    item["organization"] = e.organization
                if "title" in exp_fields:
                    item["title"] = e.title
                if "period" in exp_fields:
                    item["period"] = {"start": _month(e.start_date), "end": _month(e.end_date)}
                if "description" in exp_fields and e.description:
                    item["description"] = e.description
                items.append(item)
            out["experiences"] = items
        proj_fields = {k.split(".", 1)[1] for k in f if k.startswith("project.")}
        if proj_fields:
            items = []
            for p in profile.projects:
                if p.project_id not in sel.project_ids:
                    continue
                item = {}
                if "title" in proj_fields:
                    item["title"] = p.title
                if "summary" in proj_fields and p.summary:
                    item["summary"] = p.summary
                if "period" in proj_fields:
                    item["period"] = {"start": _month(p.start_date), "end": _month(p.end_date)}
                items.append(item)
            out["projects"] = items
        if "skills" in f:
            out["skills"] = [{"name": n, "proficiency": lvl} for n, lvl in profile.skills]
        if "target_roles" in f:
            out["target_roles"] = list(profile.target_roles)
        return out
