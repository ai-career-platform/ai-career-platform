-- T66 검산 SQL: 적재된 market_observations를 원천 공고에서 다시 세어 차이를 찾는다 (읽기 전용).
-- 결과가 0행이면 PASS. 한 행이라도 나오면 그 행이 불일치 내역이다.
-- 계약: docs/data/MARKET_METRICS_CONTRACT.md · 집계: backend/app/market_aggregation.py
--
-- reference_metrics.sql과 일부러 다른 방식(저장된 행 하나하나를 원천에서 직접 다시 세기)으로 작성했다.
-- 같은 SQL을 두 번 돌리는 것으로는 집계 로직의 실수를 잡을 수 없기 때문이다.
--
-- 바인드 매개변수: :source_id, :period, :range_start, :range_end, :as_of, :min_sample
--   적재할 때 쓴 as_of와 같은 값을 넣는다. (고정된 과거 구간은 그때의 as_of 기준이다)
WITH params AS (
    SELECT CAST(:source_id AS uuid) AS source_id, CAST(:period AS text) AS period,
           CAST(:range_start AS date) AS range_start, CAST(:range_end AS date) AS range_end,
           CAST(:as_of AS timestamptz) AS as_of, CAST(:min_sample AS integer) AS min_sample
),
stored AS (
    SELECT o.*
    FROM career.market_observations o, params prm
    WHERE o.source_id = prm.source_id AND o.period = prm.period
      AND o.observed_on >= prm.range_start AND o.observed_on < prm.range_end
),
-- 원천 공고 1건마다 KST 게시일을 붙인다 (계약 §3.1·§3.2)
src AS (
    SELECT p.job_posting_id, p.job_role_id,
           (p.published_at AT TIME ZONE 'Asia/Seoul')::date AS published_day
    FROM career.job_postings p, params prm
    WHERE p.source_id = prm.source_id
      AND p.status <> 'draft'
      AND p.published_at IS NOT NULL
      AND p.published_at <= prm.as_of
      AND p.created_at <= prm.as_of
),
-- 저장된 행의 구간 [observed_on, 다음 구간 시작)
stored_span AS (
    SELECT s.*, (s.observed_on + ('1 ' || s.period)::interval)::date AS span_end
    FROM stored s
)
-- 1) 같은 키가 두 번 이상 저장됨 (NULL 직무 포함, 계약 §5)
SELECT 'duplicate_key' AS check_name, s.observed_on, s.job_role_id, s.skill_id, s.metric_code,
       count(*)::numeric AS stored_value, 1::numeric AS recomputed_value
FROM stored s
GROUP BY s.observed_on, s.job_role_id, s.skill_id, s.metric_code
HAVING count(*) > 1

UNION ALL
-- 2) 공고 수가 원천과 다름
SELECT 'posting_count_mismatch', s.observed_on, s.job_role_id, s.skill_id, s.metric_code,
       s.metric_value,
       (SELECT count(*) FROM src
        WHERE src.published_day >= s.observed_on AND src.published_day < s.span_end
          AND (s.job_role_id IS NULL OR src.job_role_id = s.job_role_id))::numeric
FROM stored_span s
WHERE s.metric_code = 'posting_count'
  AND s.metric_value <> (SELECT count(*) FROM src
                         WHERE src.published_day >= s.observed_on AND src.published_day < s.span_end
                           AND (s.job_role_id IS NULL OR src.job_role_id = s.job_role_id))

UNION ALL
-- 3) 기술 비율이 원천과 다름 (분모 = 같은 범위 공고 수, 분자 = 그 기술 요구 공고 수)
SELECT 'skill_share_mismatch', x.observed_on, x.job_role_id, x.skill_id, x.metric_code, x.metric_value, x.recomputed
FROM (
    SELECT s.observed_on, s.job_role_id, s.skill_id, s.metric_code, s.metric_value,
           CASE WHEN d.n = 0 THEN NULL ELSE round(k.k::numeric / d.n, 4) END AS recomputed,
           d.n
    FROM stored_span s
    CROSS JOIN params prm
    CROSS JOIN LATERAL (
        SELECT count(*) AS n FROM src
        WHERE src.published_day >= s.observed_on AND src.published_day < s.span_end
          AND (s.job_role_id IS NULL OR src.job_role_id = s.job_role_id)
    ) d
    CROSS JOIN LATERAL (
        SELECT count(*) AS k FROM src
        JOIN career.job_posting_skills ps ON ps.job_posting_id = src.job_posting_id
        WHERE ps.skill_id = s.skill_id AND ps.created_at <= prm.as_of
          AND src.published_day >= s.observed_on AND src.published_day < s.span_end
          AND (s.job_role_id IS NULL OR src.job_role_id = s.job_role_id)
    ) k
    WHERE s.metric_code = 'skill_demand_share'
) x, params prm
WHERE x.recomputed IS DISTINCT FROM x.metric_value OR x.n < prm.min_sample

UNION ALL
-- 4) 원천에 공고가 있는 완료 구간인데 전체 시장 공고 수 행이 없음 (누락)
SELECT 'missing_bucket', b.bucket, NULL::uuid, NULL::uuid, 'posting_count', NULL::numeric, b.n::numeric
FROM (
    SELECT date_trunc(prm.period, src.published_day::timestamp)::date AS bucket, count(*) AS n
    FROM src, params prm
    GROUP BY 1
) b, params prm
WHERE b.bucket >= prm.range_start AND b.bucket < prm.range_end
  AND (b.bucket + ('1 ' || prm.period)::interval)::date <= (prm.as_of AT TIME ZONE 'Asia/Seoul')::date
  AND NOT EXISTS (SELECT 1 FROM stored s
                  WHERE s.observed_on = b.bucket AND s.metric_code = 'posting_count' AND s.job_role_id IS NULL)
ORDER BY 1, 2
