"""T72 행동 이벤트 저장. T31 요청 Session과 같은 사용자 행 잠금(lock_user)·최신 동의 조회를 재사용한다."""
from sqlalchemy.dialects.postgresql import insert

from app.models.behavior import BehaviorEvent
from app.repositories.privacy import SqlPrivacyRepository


class SqlBehaviorEventRepository(SqlPrivacyRepository):
    def insert_event(self, event_id, user_id, event_code, event_at, metadata) -> bool:
        """같은 기본키가 이미 있으면 아무것도 하지 않고 False (중복 요청)."""
        stmt = insert(BehaviorEvent).values(
            event_id=event_id, user_id=user_id, event_code=event_code, event_at=event_at, metadata_=metadata,
        ).on_conflict_do_nothing(index_elements=[BehaviorEvent.event_id]).returning(BehaviorEvent.event_id)
        return self.session.execute(stmt).first() is not None
