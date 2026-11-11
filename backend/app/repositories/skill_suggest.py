"""T139 실제 DB 출처: `career.skills` 활성 기술만 읽는다 (읽기 전용 SELECT).

T137 별칭·상태·대체 코드 표는 아직 migration 이 없으므로 여기서는 별칭이 없다(`alias_source=none`).
비활성(is_active=false) 기술은 T138 정리 결과 폐기·병합된 코드이므로 후보에서 뺀다.
"""
from sqlalchemy import Boolean, String, Uuid, column, select, table
from sqlalchemy.orm import Session

from app.services.skill_suggest import MAX_SOURCE_ROWS, TaxonomyEntry

skills = table(
    "skills", column("skill_id", Uuid), column("code", String), column("name", String),
    column("is_active", Boolean), schema="career",
)


class SqlSkillSource:
    name = "career.skills"

    def __init__(self, session: Session) -> None:
        self._db = session

    def entries(self) -> list[TaxonomyEntry]:
        s = skills.c
        # MAX_SOURCE_ROWS+1 까지 읽어 너무 큰 표는 서비스가 503 으로 거절하게 한다(전체 적재 방지).
        stmt = (select(s.skill_id, s.code, s.name).where(s.is_active.is_(True))
                .order_by(s.code).limit(MAX_SOURCE_ROWS + 1))
        return [TaxonomyEntry(code=r.code, name=r.name, skill_id=r.skill_id)
                for r in self._db.execute(stmt).mappings()]
