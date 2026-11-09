from uuid import UUID
from app.core.errors import AppError, ErrorCode
from app.repositories.career_history import CareerHistoryRepository
from app.schemas.career_history import ExperienceInput, ExperiencePatch, ProjectInput, ProjectPatch

class CareerHistoryService:
    def __init__(self, repo: CareerHistoryRepository): self.repo = repo
    def list_experiences(self, user_id): return self.repo.list_experiences(user_id)
    def create_experience(self, user_id, data): return self.repo.create_experience(user_id, data)
    def update_experience(self, user_id, item_id, data):
        try: result = self.repo.update_experience(user_id, item_id, data)
        except ValueError: raise AppError(ErrorCode.VALIDATION_FAILED) from None
        if result is None: raise AppError(ErrorCode.NOT_FOUND)
        return result
    def delete_experience(self, user_id, item_id):
        if not self.repo.delete_experience(user_id, item_id): raise AppError(ErrorCode.NOT_FOUND)
    def list_projects(self, user_id): return self.repo.list_projects(user_id)
    def create_project(self, user_id, data):
        try: return self.repo.create_project(user_id, data)
        except ValueError: raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="unknown skill") from None
    def update_project(self, user_id, item_id, data):
        try: result = self.repo.update_project(user_id, item_id, data)
        except ValueError: raise AppError(ErrorCode.VALIDATION_FAILED) from None
        if result is None: raise AppError(ErrorCode.NOT_FOUND)
        return result
    def delete_project(self, user_id, item_id):
        if not self.repo.delete_project(user_id, item_id): raise AppError(ErrorCode.NOT_FOUND)
