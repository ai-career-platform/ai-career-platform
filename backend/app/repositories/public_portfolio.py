"""T129 공개 포트폴리오 DB 접근. 표: database/migrations/0007_public_portfolio.sql (T128 설계, PR #349).

- 소유자 쿼리는 모두 user_id 로 범위를 묶는다(본인 선택·링크만). 값은 바인딩 변수로만 전달한다.
- 공개 조회는 token_hash(UNIQUE) 로 한 행만 찾는다. 토큰 원문은 이 모듈에 들어오지 않는다.
- 동시성: 선택·동의·링크 추가·철회는 사용자 선택 행(public_profile_selections)을 `FOR UPDATE` 로 잠근 뒤 검사한다
  (활성 링크 3개 한도는 시간 조건이라 CHECK 로 못 막으므로 이 잠금 아래에서 센다).
- 각 쓰기 메서드는 스스로 커밋한다. 로그에 개인정보·토큰을 남기지 않는다(이 모듈은 로그를 쓰지 않음).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.public_portfolio import (
    CONSENT_CODE, Experience, ProfileData, Project, Selection, ShareLink,
)

_LINK_COLUMNS = "link_id, user_id, token_hash, created_at, expires_at, revoked_at, view_count"


def _link(r) -> ShareLink:
    return ShareLink(link_id=r.link_id, user_id=r.user_id, token_hash=r.token_hash.strip(), created_at=r.created_at,
                     expires_at=r.expires_at, revoked_at=r.revoked_at, views=r.view_count)


class SqlPortfolioRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    # ------------------------------------------------------------ 내부
    def _selection(self, user_id: UUID, *, lock: bool = False) -> Selection | None:
        row = self.db.execute(text(
            "SELECT fields, alias, version, confirmed_version FROM career.public_profile_selections WHERE user_id = :u"
            + (" FOR UPDATE" if lock else "")), {"u": user_id}).first()
        if row is None:
            return None
        exp = self.db.execute(text("SELECT experience_id FROM career.public_profile_selected_experiences "
                                   "WHERE user_id = :u"), {"u": user_id}).scalars().all()
        proj = self.db.execute(text("SELECT project_id FROM career.public_profile_selected_projects "
                                    "WHERE user_id = :u"), {"u": user_id}).scalars().all()
        return Selection(fields=frozenset(row.fields), experience_ids=frozenset(exp), project_ids=frozenset(proj),
                         version=row.version, confirmed_version=row.confirmed_version, alias=row.alias)

    def _policy_version(self, requested: str | None, now: datetime) -> str | None:
        """요청한 버전이 등록돼 있으면 그것, None 이면 지금 시행 중인 최신 public_profile 버전. 없으면 None."""
        if requested is not None:
            found = self.db.execute(text("SELECT version FROM career.consent_policies "
                                         "WHERE policy_code = :c AND version = :v"),
                                    {"c": CONSENT_CODE, "v": requested}).scalar()
            return found
        return self.db.execute(text(
            "SELECT version FROM career.consent_policies WHERE policy_code = :c AND effective_at <= :now "
            "ORDER BY effective_at DESC, version DESC LIMIT 1"), {"c": CONSENT_CODE, "now": now}).scalar()

    def _record_consent(self, user_id: UUID, policy_version: str, granted: bool, selection_version: int,
                        now: datetime) -> None:
        consent_id = self.db.execute(text(
            "INSERT INTO career.user_consents (user_id, policy_code, policy_version, granted, recorded_at) "
            "VALUES (:u, :c, :v, :g, :now) RETURNING consent_id"),
            {"u": user_id, "c": CONSENT_CODE, "v": policy_version, "g": granted, "now": now}).scalar_one()
        self.db.execute(text("INSERT INTO career.public_profile_consent_records (consent_id, user_id, selection_version) "
                             "VALUES (:id, :u, :sv)"), {"id": consent_id, "u": user_id, "sv": selection_version})

    # ------------------------------------------------------------ 소유자
    def get_selection(self, user_id: UUID) -> Selection:
        return self._selection(user_id) or Selection()

    def save_selection(self, user_id, fields, experience_ids, project_ids, alias, expected_version, now):
        db = self.db
        params = {"u": user_id, "fields": sorted(fields), "alias": alias, "now": now, "expected": expected_version}
        try:
            current = self._selection(user_id, lock=True)
            if current is None:
                if expected_version != 1:
                    db.rollback()
                    return "conflict"
                saved = db.execute(text(
                    "INSERT INTO career.public_profile_selections (user_id, fields, alias, version, created_at, updated_at) "
                    "VALUES (:u, CAST(:fields AS text[]), :alias, 2, :now, :now) "
                    "ON CONFLICT (user_id) DO NOTHING RETURNING version"), params).scalar()
            else:
                saved = db.execute(text(
                    "UPDATE career.public_profile_selections SET fields = CAST(:fields AS text[]), alias = :alias, "
                    "version = version + 1, confirmed_version = NULL, updated_at = :now "
                    "WHERE user_id = :u AND version = :expected RETURNING version"), params).scalar()
            if saved is None:                 # 동시에 다른 탭이 먼저 저장
                db.rollback()
                return "conflict"
            db.execute(text("DELETE FROM career.public_profile_selected_experiences WHERE user_id = :u"), {"u": user_id})
            db.execute(text("DELETE FROM career.public_profile_selected_projects WHERE user_id = :u"), {"u": user_id})
            for experience_id in sorted(experience_ids):
                db.execute(text("INSERT INTO career.public_profile_selected_experiences (user_id, experience_id) "
                                "VALUES (:u, :id)"), {"u": user_id, "id": experience_id})
            for project_id in sorted(project_ids):
                db.execute(text("INSERT INTO career.public_profile_selected_projects (user_id, project_id) "
                                "VALUES (:u, :id)"), {"u": user_id, "id": project_id})
            db.commit()
        except IntegrityError:                # 복합 FK: 본인 항목이 아니거나 방금 지워진 항목
            db.rollback()
            return "not_owned"
        return Selection(fields=frozenset(fields), experience_ids=frozenset(experience_ids),
                         project_ids=frozenset(project_ids), version=saved, confirmed_version=None, alias=alias)

    def confirm(self, user_id, version, policy_version, now):
        db = self.db
        current = self._selection(user_id, lock=True)
        if (current.version if current else 1) != version:
            db.rollback()
            return "conflict"
        if current is None or not current.fields:
            db.rollback()
            return "empty"
        resolved = self._policy_version(policy_version, now)
        if resolved is None:
            db.rollback()
            return "no_policy"
        db.execute(text("UPDATE career.public_profile_selections SET confirmed_version = version, updated_at = :now "
                        "WHERE user_id = :u"), {"u": user_id, "now": now})
        self._record_consent(user_id, resolved, True, current.version, now)
        db.commit()
        return Selection(current.fields, current.experience_ids, current.project_ids, version=current.version,
                         confirmed_version=current.version, alias=current.alias)

    def withdraw(self, user_id, policy_version, now):
        db = self.db
        current = self._selection(user_id, lock=True)
        previous = current.version if current else 1
        db.execute(text(
            "INSERT INTO career.public_profile_selections (user_id, fields, alias, version, created_at, updated_at) "
            "VALUES (:u, '{}', NULL, :v, :now, :now) ON CONFLICT (user_id) DO UPDATE SET fields = '{}', alias = NULL, "
            "version = EXCLUDED.version, confirmed_version = NULL, updated_at = EXCLUDED.updated_at"),
            {"u": user_id, "v": previous + 1, "now": now})
        db.execute(text("DELETE FROM career.public_profile_selected_experiences WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM career.public_profile_selected_projects WHERE user_id = :u"), {"u": user_id})
        db.execute(text("UPDATE career.public_profile_links SET revoked_at = GREATEST(:now, created_at) "
                        "WHERE user_id = :u AND revoked_at IS NULL"), {"u": user_id, "now": now})
        resolved = self._policy_version(policy_version, now)
        if resolved is not None:              # 약관 행이 없으면 동의한 적도 없다 — 철회 기록만 생략
            self._record_consent(user_id, resolved, False, previous, now)
        db.commit()

    def list_links(self, user_id):
        rows = self.db.execute(text(f"SELECT {_LINK_COLUMNS} FROM career.public_profile_links WHERE user_id = :u "
                                    "ORDER BY created_at DESC, link_id"), {"u": user_id})
        return [_link(r) for r in rows]

    def add_link(self, user_id, token_hash, now, expires_at, max_active):
        db = self.db
        current = self._selection(user_id, lock=True)      # 같은 사용자의 동시 생성을 직렬화
        if current is None or not current.consented:
            db.rollback()
            return "not_consented"
        active = db.execute(text("SELECT count(*) FROM career.public_profile_links "
                                 "WHERE user_id = :u AND revoked_at IS NULL AND expires_at > :now"),
                            {"u": user_id, "now": now}).scalar_one()
        if active >= max_active:
            db.rollback()
            return "limit"
        row = db.execute(text(
            "INSERT INTO career.public_profile_links (user_id, token_hash, created_at, expires_at) "
            f"VALUES (:u, :h, :now, :exp) RETURNING {_LINK_COLUMNS}"),
            {"u": user_id, "h": token_hash, "now": now, "exp": expires_at}).first()
        db.commit()
        return _link(row)

    def revoke_link(self, user_id, link_id, now):
        found = self.db.execute(text(
            "UPDATE career.public_profile_links SET revoked_at = COALESCE(revoked_at, GREATEST(:now, created_at)) "
            "WHERE user_id = :u AND link_id = :id RETURNING link_id"),
            {"u": user_id, "id": link_id, "now": now}).first()
        self.db.commit()
        return found is not None

    # ------------------------------------------------------------ 공개 조회
    def open_link(self, token_hash, now):
        db = self.db
        row = db.execute(text(
            "UPDATE career.public_profile_links l SET view_count = l.view_count + 1 "
            "FROM career.public_profile_selections s "
            "WHERE l.token_hash = :h AND l.revoked_at IS NULL AND l.expires_at > :now "
            "AND s.user_id = l.user_id AND s.confirmed_version = s.version AND cardinality(s.fields) > 0 "
            f"RETURNING {', '.join('l.' + c.strip() for c in _LINK_COLUMNS.split(','))}"),
            {"h": token_hash, "now": now}).first()
        if row is None:
            db.rollback()
            return None
        selection = self._selection(row.user_id)
        db.commit()
        if selection is None or not selection.consented:
            return None
        return _link(row), selection


class SqlProfileSource:
    """공개 화면이 그릴 현재 프로필(표: users·user_profiles·user_experiences·user_projects·user_skills·user_target_roles)."""

    def __init__(self, session: Session) -> None:
        self.db = session

    def load(self, user_id: UUID) -> ProfileData | None:
        db = self.db
        base = db.execute(text(
            "SELECT u.display_name, u.email, p.headline, p.bio, p.location_text FROM career.users u "
            "LEFT JOIN career.user_profiles p ON p.user_id = u.user_id WHERE u.user_id = :u AND u.status = 'active'"),
            {"u": user_id}).first()
        if base is None:
            return None
        experiences = tuple(Experience(r.experience_id, r.organization, r.title, r.start_date, r.end_date, r.description)
                            for r in db.execute(text(
                                "SELECT experience_id, organization, title, start_date, end_date, description "
                                "FROM career.user_experiences WHERE user_id = :u "
                                "ORDER BY start_date DESC NULLS LAST, experience_id"), {"u": user_id}))
        projects = tuple(Project(r.project_id, r.title, r.summary, r.start_date, r.end_date)
                         for r in db.execute(text(
                             "SELECT project_id, title, summary, start_date, end_date FROM career.user_projects "
                             "WHERE user_id = :u ORDER BY start_date DESC NULLS LAST, project_id"), {"u": user_id}))
        skills = tuple((r.name, r.proficiency) for r in db.execute(text(
            "SELECT s.name, us.proficiency FROM career.user_skills us JOIN career.skills s ON s.skill_id = us.skill_id "
            "WHERE us.user_id = :u ORDER BY s.name, s.skill_id"), {"u": user_id}))
        roles = tuple(db.execute(text(
            "SELECT r.name FROM career.user_target_roles t JOIN career.job_roles r ON r.job_role_id = t.job_role_id "
            "WHERE t.user_id = :u ORDER BY t.priority"), {"u": user_id}).scalars())
        return ProfileData(display_name=base.display_name, headline=base.headline, bio=base.bio,
                           location_text=base.location_text, email=base.email, experiences=experiences,
                           projects=projects, skills=skills, target_roles=roles)
