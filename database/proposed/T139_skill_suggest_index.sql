-- T139 PROPOSED (not a migration; never applied to Staging/production without PM + DBA approval).
-- Supports the T139 suggest source query:
--   SELECT skill_id, code, name FROM career.skills WHERE is_active ORDER BY code LIMIT 5001
-- At the T10 seed size (~70 rows) PostgreSQL prefers a sequential scan, so this index is NOT needed today.
-- It becomes useful only if the skills table grows past a few thousand rows. Alias search indexes belong to the
-- T137 taxonomy_aliases table (alias_norm), which is itself still a proposal.
CREATE INDEX IF NOT EXISTS ix_skills_t139_active_code ON career.skills (code) WHERE is_active;

-- rollback
-- DROP INDEX IF EXISTS career.ix_skills_t139_active_code;
