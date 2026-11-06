from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 제약 이름을 규칙으로 고정해 Migration SQL과 ORM 메타데이터의 이름이 어긋나지 않게 합니다.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 스키마 이름은 T09/T08의 확정 결과(예: career)에 맞춰 모델에서 지정합니다.


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
