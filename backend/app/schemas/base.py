from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """SQLAlchemy 객체에서 바로 응답을 만들 수 있는 Pydantic 기본 클래스.

    사용: `ProfileResponse.model_validate(orm_obj)` 또는 라우터의 `response_model`.
    """

    model_config = ConfigDict(from_attributes=True)
