"""T31 uses the same request-scoped T14 Session and existing career tables."""
from uuid import UUID
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from app.models.auth import User, UserConsent, ConsentPolicy, AuthSession, AccountDeletionRequest
from app.models.behavior import BehaviorEvent
from app.repositories.auth import SqlAuthRepository
from app.schemas.privacy import Consent, DeletionRequest

class SqlPrivacyRepository:
    def __init__(self, session: Session):
        self.session = session

    def lock_user(self, user_id: UUID):
        return self.session.scalar(select(User).where(User.user_id == user_id)
            .with_for_update().execution_options(populate_existing=True))

    def current_policy(self, code, now):
        return next((p for p in SqlAuthRepository(self.session).current_policies(now)
                     if p.policy_code == code), None)

    def list_consents(self, user_id):
        rows = self.session.execute(select(UserConsent, ConsentPolicy.is_required).join(
            ConsentPolicy, (ConsentPolicy.policy_code == UserConsent.policy_code)
            & (ConsentPolicy.version == UserConsent.policy_version))
            .where(UserConsent.user_id == user_id)
            .order_by(UserConsent.recorded_at.desc(), UserConsent.consent_id.desc())).all()
        return [self.consent_dto(c, required) for c, required in rows]

    @staticmethod
    def consent_dto(row, required):
        return Consent(consent_id=row.consent_id, is_required=required,
            policy_code=row.policy_code, policy_version=row.policy_version,
            granted=row.granted, recorded_at=row.recorded_at)

    def latest_consent(self, user_id, code):
        return self.session.scalar(select(UserConsent).where(
            UserConsent.user_id == user_id, UserConsent.policy_code == code)
            .order_by(UserConsent.recorded_at.desc(), UserConsent.consent_id.desc()).limit(1))

    def add_consent(self, user_id, body, now):
        row = UserConsent(user_id=user_id, policy_code=body.policy_code,
            policy_version=body.policy_version, granted=body.granted, recorded_at=now)
        self.session.add(row)
        self.session.flush()
        return self.consent_dto(row, False)

    def delete_behavior_events(self, user_id, event_codes):
        """T72/T71 §6: 철회와 같은 트랜잭션에서 그 정책으로 모은 이벤트를 지운다(lock_user 이후 호출)."""
        result = self.session.execute(delete(BehaviorEvent).where(
            BehaviorEvent.user_id == user_id, BehaviorEvent.event_code.in_(sorted(event_codes))))
        return result.rowcount

    def get_deletion(self, user_id):
        row = self.session.scalar(select(AccountDeletionRequest).where(
            AccountDeletionRequest.user_id == user_id, AccountDeletionRequest.status == "requested"))
        return DeletionRequest.model_validate(row) if row else None

    def add_deletion(self, user_id, now):
        row = AccountDeletionRequest(user_id=user_id, status="requested", requested_at=now,
                                     scheduled_purge_at=None, completed_at=None)
        self.session.add(row)
        self.session.flush()
        return DeletionRequest.model_validate(row)

    def disable_and_revoke(self, user, now):
        user.status = "disabled"
        user.updated_at = now
        self.session.execute(update(AuthSession).where(
            AuthSession.user_id == user.user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now))
        self.session.flush()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()
