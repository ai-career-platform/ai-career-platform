-- Purpose: T65 (Redmine #1597) 채용시장 지표 계약. skill_demand_share를 기술별로 저장하도록
-- Purpose: market_observations / market_forecasts에 skill_id 차원을 추가하고 지표 값 범위를 DB에서 막는다.
-- Recovery: 추가 컬럼은 NULL 허용이라 기존 행·쿼리는 그대로 동작한다. 되돌릴 때는 새 migration에서
-- Recovery: ix_market_observations_1을 0001 정의로 다시 만들고 CHECK를 제거한다(컬럼 제거는 Destructive-Approval 필요).
-- Recovery: 적용 전 기존 행이 새 CHECK를 어기면 이 migration 전체가 롤백되며, 계약에 맞게 행을 정리한 뒤 다시 실행한다.
-- Source: docs/data/MARKET_METRICS_CONTRACT.md (T65). PM/JM 승인: 2026-11-09 Slack (조정민) "DB 명세 migration으로 변경 가능".
-- Note: job_role_id/skill_id가 NULL인 행의 UNIQUE 중복(NULLS DISTINCT)은 PM 결정에 따라 이번에 바꾸지 않는다.
-- Note: 적재(T66)는 같은 키를 먼저 지우고 넣거나 IS NOT DISTINCT FROM 조건으로 갱신해 중복을 만들지 않는다.

ALTER TABLE career.market_observations
    ADD COLUMN skill_id uuid REFERENCES career.skills (skill_id) ON DELETE RESTRICT;
ALTER TABLE career.market_forecasts
    ADD COLUMN skill_id uuid REFERENCES career.skills (skill_id) ON DELETE RESTRICT;

-- 기술별 지표는 skill_id가 반드시 있고, 기술과 무관한 지표에는 skill_id가 없다.
ALTER TABLE career.market_observations
    ADD CONSTRAINT ck_market_observations_skill_dimension
    CHECK ((metric_code = 'skill_demand_share') = (skill_id IS NOT NULL));
ALTER TABLE career.market_forecasts
    ADD CONSTRAINT ck_market_forecasts_skill_dimension
    CHECK ((metric_code = 'skill_demand_share') = (skill_id IS NOT NULL));

-- 관측값 범위: 공고 수는 0 이상의 정수, 비율은 0~1.
ALTER TABLE career.market_observations
    ADD CONSTRAINT ck_market_observations_value_range
    CHECK (
        (metric_code <> 'posting_count' OR (metric_value >= 0 AND metric_value = trunc(metric_value)))
        AND (metric_code <> 'skill_demand_share' OR metric_value BETWEEN 0 AND 1)
    );

-- 같은 출처·직무·기간에 기술마다 한 행씩 들어갈 수 있도록 고유 키를 둘로 나눈다.
-- 기술 없는 지표는 0001과 똑같은 키·동작을 유지하고(부분 인덱스), 기술별 지표는 skill_id까지 포함한 키를 쓴다.
-- skill_id를 한 인덱스에 NULL 허용 열로 넣으면 기술 없는 지표의 중복을 막지 못하므로 이렇게 나눈다.
DROP INDEX career.ix_market_observations_1;
CREATE UNIQUE INDEX ix_market_observations_1
    ON career.market_observations (source_id, job_role_id, metric_code, period, observed_on)
    WHERE skill_id IS NULL;
CREATE UNIQUE INDEX ix_market_observations_3
    ON career.market_observations (source_id, job_role_id, skill_id, metric_code, period, observed_on)
    WHERE skill_id IS NOT NULL;
CREATE INDEX ix_market_observations_4 ON career.market_observations (skill_id, metric_code, observed_on);
CREATE INDEX ix_market_forecasts_3 ON career.market_forecasts (skill_id, metric_code, forecast_for);

COMMENT ON COLUMN career.market_observations.skill_id IS
    'T65: skill_demand_share 전용 기술 차원. 다른 지표는 NULL';
COMMENT ON COLUMN career.market_forecasts.skill_id IS
    'T65: skill_demand_share 예측 전용 기술 차원. 다른 지표는 NULL';
