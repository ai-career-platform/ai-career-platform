-- T65 채용시장 지표 검산 SQL (읽기 전용). 계약: docs/data/MARKET_METRICS_CONTRACT.md
--
-- 한 출처(source_id)의 한 집계 단위(period)에 대해 [range_start, range_end) 구간의
-- posting_count / skill_demand_share 관측값을 계산한다. 쓰기는 하지 않는다.
-- T66 집계 Pipeline은 이 결과와 차이 0이어야 한다(검산 기준).
--
-- 바인드 매개변수 (SQLAlchemy text() 형식):
--   :source_id    uuid         집계할 출처
--   :period       text         'day' | 'week' | 'month'
--   :range_start  date         포함. 구간 시작일(KST)로 맞춰 준다 (주=월요일, 월=1일)
--   :range_end    date         제외
--   :as_of        timestamptz  계산 기준 시각. 이 시각까지 알 수 있던 데이터만 쓴다(시점 누수 방지)
--   :min_sample   integer      skill_demand_share를 낼 최소 공고 수 (계약 기본값 5)
WITH params AS (
    SELECT CAST(:source_id AS uuid)       AS source_id,
           CAST(:period AS text)          AS period,
           CAST(:range_start AS date)     AS range_start,
           CAST(:range_end AS date)       AS range_end,
           CAST(:as_of AS timestamptz)    AS as_of,
           (CAST(:as_of AS timestamptz) AT TIME ZONE 'Asia/Seoul')::date AS as_of_day,
           CAST(:min_sample AS integer)   AS min_sample
),
-- §3.1 집계 대상 공고: 게시된 적 있는 공고(published/closed), as_of까지 게시·저장된 것
eligible AS (
    SELECT p.job_posting_id,
           p.job_role_id,
           date_trunc(prm.period, p.published_at AT TIME ZONE 'Asia/Seoul')::date AS bucket
    FROM career.job_postings p
    CROSS JOIN params prm
    WHERE p.source_id = prm.source_id
      AND p.status IN ('published', 'closed')
      AND p.published_at IS NOT NULL
      AND p.published_at <= prm.as_of
      AND p.created_at <= prm.as_of
),
-- §3.2 집계 구간: KST 기준 구간 시작일
buckets AS (
    SELECT g::date AS bucket,
           (g + ('1 ' || prm.period)::interval)::date AS bucket_end
    FROM params prm,
         generate_series(date_trunc(prm.period, prm.range_start::timestamp),
                         prm.range_end::timestamp - interval '1 day',
                         ('1 ' || prm.period)::interval) AS g
),
-- §3.4 완료되고(as_of 이전에 끝난) 관측된 구간만 값을 낸다. 관측 = 공고가 있거나 수집 성공 기록이 있음
covered AS (
    SELECT b.bucket
    FROM buckets b
    CROSS JOIN params prm
    WHERE b.bucket >= prm.range_start
      AND b.bucket < prm.range_end
      AND b.bucket_end <= prm.as_of_day
      AND (
          EXISTS (SELECT 1 FROM eligible e WHERE e.bucket = b.bucket)
          OR EXISTS (
              SELECT 1
              FROM career.ingestion_runs r
              WHERE r.source_id = prm.source_id
                AND r.status = 'succeeded'
                AND r.ended_at IS NOT NULL
                AND r.ended_at <= prm.as_of
                AND (r.ended_at AT TIME ZONE 'Asia/Seoul')::date >= b.bucket
                AND (r.ended_at AT TIME ZONE 'Asia/Seoul')::date < b.bucket_end
          )
      )
),
-- §3.3 범위: 전체 시장(NULL) + as_of까지 이 출처에 공고가 한 건이라도 있었던 직무.
-- 조회 구간과 무관하게 정해야 일부 구간만 다시 계산해도(T66) 전체 재계산과 같은 결과가 나온다.
scopes AS (
    SELECT NULL::uuid AS job_role_id
    UNION
    SELECT e.job_role_id
    FROM eligible e
    WHERE e.job_role_id IS NOT NULL
),
counts AS (
    SELECT c.bucket, s.job_role_id, count(e.job_posting_id) AS n
    FROM covered c
    CROSS JOIN scopes s
    LEFT JOIN eligible e
           ON e.bucket = c.bucket
          AND (s.job_role_id IS NULL OR e.job_role_id = s.job_role_id)
    GROUP BY c.bucket, s.job_role_id
),
skill_counts AS (
    SELECT c.bucket, s.job_role_id, ps.skill_id, count(DISTINCT e.job_posting_id) AS k
    FROM covered c
    CROSS JOIN scopes s
    JOIN eligible e
      ON e.bucket = c.bucket
     AND (s.job_role_id IS NULL OR e.job_role_id = s.job_role_id)
    JOIN career.job_posting_skills ps ON ps.job_posting_id = e.job_posting_id
    CROSS JOIN params prm
    WHERE ps.created_at <= prm.as_of
    GROUP BY c.bucket, s.job_role_id, ps.skill_id
)
SELECT prm.source_id,
       n.job_role_id,
       NULL::uuid                 AS skill_id,
       'posting_count'::text      AS metric_code,
       prm.period,
       n.bucket                   AS observed_on,
       n.n::numeric               AS metric_value
FROM counts n
CROSS JOIN params prm
UNION ALL
SELECT prm.source_id,
       k.job_role_id,
       k.skill_id,
       'skill_demand_share'::text,
       prm.period,
       k.bucket,
       round(k.k::numeric / n.n, 4)
FROM skill_counts k
JOIN counts n
  ON n.bucket = k.bucket
 AND n.job_role_id IS NOT DISTINCT FROM k.job_role_id
CROSS JOIN params prm
WHERE n.n >= prm.min_sample
ORDER BY 6, 4, 2 NULLS FIRST, 3
