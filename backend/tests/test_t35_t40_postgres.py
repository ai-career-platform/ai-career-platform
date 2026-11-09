"""T35~T40 실제 PostgreSQL 쓰기 E2E. TEST_DATABASE_URL이 있을 때만 실행한다."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repositories.bookmarks import SqlBookmarkRepository
from app.repositories.career_history import SqlCareerHistoryRepository
from app.repositories.target_roles import SqlTargetRoleRepository
from app.schemas.career_history import ExperienceInput, ExperiencePatch, ProjectInput, ProjectPatch
from app.schemas.target_roles import TargetRoleItem

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not configured")


def test_career_workspace_full_crud_against_postgres():
    engine = create_engine(URL)
    user_id = uuid4()
    email = f"t35-t40-{user_id}@example.test"
    with Session(engine) as db:
        db.execute(text("""INSERT INTO career.users
            (user_id, email, email_canonical, display_name, status)
            VALUES (:id, :email, :email, 'E2E User', 'active')"""), {"id": user_id, "email": email})
        db.commit()
        try:
            role_id = db.execute(text("SELECT job_role_id FROM career.job_roles WHERE is_active ORDER BY code LIMIT 1")).scalar_one()
            skill_id = db.execute(text("SELECT skill_id FROM career.skills WHERE is_active ORDER BY code LIMIT 1")).scalar_one()
            posting_id = db.execute(text("SELECT job_posting_id FROM career.job_postings WHERE status IN ('published','closed') ORDER BY job_posting_id LIMIT 1")).scalar_one()

            targets = SqlTargetRoleRepository(db)
            saved_targets = targets.replace(user_id, [TargetRoleItem(job_role_id=role_id, priority=1)])
            assert saved_targets and saved_targets[0].job_role.job_role_id == role_id
            assert len(targets.list_for_user(user_id)) == 1

            history = SqlCareerHistoryRepository(db)
            experience = history.create_experience(user_id, ExperienceInput(organization="E2E Org", title="Engineer"))
            experience = history.update_experience(user_id, experience.experience_id, ExperiencePatch(title="Senior Engineer"))
            assert experience and experience.title == "Senior Engineer"

            project = history.create_project(user_id, ProjectInput(title="E2E Project", skill_ids=[skill_id]))
            assert project and [item.skill_id for item in project.skills] == [skill_id]
            project = history.update_project(user_id, project.project_id, ProjectPatch(summary="Integrated"))
            assert project and project.summary == "Integrated"

            bookmarks = SqlBookmarkRepository(db)
            assert bookmarks.add(user_id, posting_id)
            assert bookmarks.add(user_id, posting_id)  # idempotent
            rows = bookmarks.list(user_id, None, 20, datetime.now(UTC))
            assert [row.posting.job_posting_id for row in rows] == [posting_id]
            bookmarks.remove(user_id, posting_id)
            bookmarks.remove(user_id, posting_id)  # idempotent
            assert bookmarks.list(user_id, None, 20, datetime.now(UTC)) == []

            assert history.delete_experience(user_id, experience.experience_id)
            assert history.delete_project(user_id, project.project_id)
            assert history.list_experiences(user_id) == []
            assert history.list_projects(user_id) == []
        finally:
            db.execute(text("DELETE FROM career.users WHERE user_id = :id"), {"id": user_id})
            db.commit()
    engine.dispose()
