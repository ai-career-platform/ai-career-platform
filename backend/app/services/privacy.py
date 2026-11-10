"""Append-only consents and atomic deletion intake, without physical deletion."""
from datetime import UTC, datetime
from sqlalchemy.exc import SQLAlchemyError
from app.core.errors import AppError, ErrorCode
from app.schemas.behavior_events import TRACKING_EVENTS, TRACKING_POLICY

class PrivacyService:
    def __init__(self, repo):
        self.repo = repo

    def storage_error(self, exc):
        self.repo.rollback()
        return AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__)

    def list_consents(self, user_id):
        try:
            return self.repo.list_consents(user_id)
        except SQLAlchemyError as exc:
            raise self.storage_error(exc) from None

    def record_consent(self, user_id, body):
        try:
            user = self.repo.lock_user(user_id)
            if user is None or user.status != "active":
                raise AppError(ErrorCode.UNAUTHENTICATED)
            now = datetime.now(UTC)
            policy = self.repo.current_policy(body.policy_code, now)
            if policy is None or policy.version != body.policy_version or policy.is_required:
                raise AppError(ErrorCode.VALIDATION_FAILED)
            latest = self.repo.latest_consent(user_id, body.policy_code)
            if latest is not None and latest.policy_version == body.policy_version and latest.granted == body.granted:
                result = self.repo.consent_dto(latest, False)
            else:
                result = self.repo.add_consent(user_id, body, now)
            if body.policy_code == TRACKING_POLICY and not body.granted:
                # T72/T71 §6: 같은 사용자 행 잠금 안에서, 같은 트랜잭션으로 수집 이벤트를 지운다.
                self.repo.delete_behavior_events(user_id, TRACKING_EVENTS)
            self.repo.commit()
            return result
        except AppError:
            self.repo.rollback()
            raise
        except SQLAlchemyError as exc:
            raise self.storage_error(exc) from None
        except Exception:
            self.repo.rollback()
            raise

    def get_deletion(self, user_id):
        try:
            result = self.repo.get_deletion(user_id)
            if result is None:
                raise AppError(ErrorCode.NOT_FOUND)
            return result
        except SQLAlchemyError as exc:
            raise self.storage_error(exc) from None

    def request_deletion(self, user_id):
        try:
            user = self.repo.lock_user(user_id)
            if user is None:
                raise AppError(ErrorCode.NOT_FOUND)
            if self.repo.get_deletion(user_id) is not None:
                raise AppError(ErrorCode.DELETION_ALREADY_REQUESTED)
            if user.status != "active":
                raise AppError(ErrorCode.UNAUTHENTICATED)
            now = datetime.now(UTC)
            result = self.repo.add_deletion(user_id, now)
            self.repo.disable_and_revoke(user, now)
            self.repo.commit()
            return result
        except AppError:
            self.repo.rollback()
            raise
        except SQLAlchemyError as exc:
            raise self.storage_error(exc) from None
        except Exception:
            self.repo.rollback()
            raise

    def cancel_deletion(self, user_id):
        self.get_deletion(user_id)  # unknown/not owned ->404
        # Intake disables the user and revokes every session. T15 intentionally
        # cannot reauthenticate that user. Never invent a bypass/recovery token.
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE,
                       log_detail="deletion cancellation reauthentication policy unresolved")
