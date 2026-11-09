"""T45·T47이 함께 쓰는 추천 테이블 정의 (스키마 `career`, T09 `0001_initial_schema.sql`에 이미 있음, DDL 없음).

- 공유 ORM 모델을 새로 만들지 않고 쓰는 컬럼만 `table()`로 적는다 (T17·T18과 같은 방식).
- T45 `recommendation_runs.py`(실행 생성·조회)와 T47 `recommendation_feedback.py`(피드백 기록·소유권 확인)가
  같은 정의를 쓰도록 한 곳에 둔다. 두 저장소 모듈이 서로를 순환 import하지 않게 하려는 분리다.
"""

from sqlalchemy import DateTime, Float, Integer, String, Uuid, column, table

SCHEMA = "career"
model_versions = table("model_versions", column("model_version_id", Uuid), column("model_code", String),
    column("version", String), column("kind", String), column("description", String), schema=SCHEMA)
runs = table("recommendation_runs", column("recommendation_run_id", Uuid), column("user_id", Uuid),
    column("model_version_id", Uuid), column("status", String),
    column("generated_at", DateTime(timezone=True)), schema=SCHEMA)
items = table("recommendation_items", column("recommendation_run_id", Uuid), column("job_posting_id", Uuid),
    column("rank", Integer), column("score", Float), column("reason", String), schema=SCHEMA)
feedback = table("recommendation_feedback", column("feedback_id", Uuid), column("user_id", Uuid),
    column("recommendation_run_id", Uuid), column("job_posting_id", Uuid), column("feedback", String),
    column("created_at", DateTime(timezone=True)), schema=SCHEMA)
