-- T68 E2E 검산용 스냅샷 (읽기 전용 SELECT). 일회용 E2E DB에서만 실행한다.
-- psql -X -At -v ON_ERROR_STOP=1 -c "SET default_transaction_read_only = on" -f frontend/docs/t68_db_snapshot.sql > t68_db_snapshot.json
SELECT json_build_object(
  'observations', COALESCE((
    SELECT json_agg(row_to_json(x) ORDER BY x.period, x.metric_code, x.role_code NULLS FIRST, x.skill_code NULLS FIRST, x.date)
    FROM (
      SELECT o.period, o.metric_code, o.observed_on::text AS date, o.metric_value::float8 AS value,
             r.job_role_id::text AS job_role_id, r.code AS role_code, r.name AS role_name,
             k.skill_id::text AS skill_id, k.code AS skill_code, k.name AS skill_name,
             s.code AS source_code, s.name AS source_name
      FROM career.market_observations o
      JOIN career.data_sources s USING (source_id)
      LEFT JOIN career.job_roles r USING (job_role_id)
      LEFT JOIN career.skills k USING (skill_id)
    ) x), '[]'::json),
  'empty_role', (
    SELECT json_build_object('job_role_id', r.job_role_id::text, 'name', r.name)
    FROM career.job_roles r
    WHERE NOT EXISTS (SELECT 1 FROM career.market_observations o WHERE o.job_role_id = r.job_role_id)
    ORDER BY r.code LIMIT 1)
);
