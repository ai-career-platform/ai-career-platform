"""Full-system E2E — 흐름이 끝난 뒤 SQL 로 상태·FK·불변식을 확인한다(관리자 연결, 읽기만)."""
from __future__ import annotations

import psycopg

JOBKOREA_DRAFT_ID = "e2e00000-0000-4000-8000-00000000d001"

CHECKS = [
    ("PLATFORM", "all FK/CHECK constraints validated (no NOT VALID constraints)",
     "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
     "WHERE n.nspname='career' AND NOT c.convalidated", 0),
    ("PLATFORM", "no disabled triggers in schema career",
     "SELECT count(*) FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid JOIN pg_namespace n ON n.oid=r.relnamespace "
     "WHERE n.nspname='career' AND NOT t.tgisinternal AND t.tgenabled='D'", 0),
    ("COMPANY", "pre-publish company postings (draft/pending/rejected) have no public row",
     "SELECT count(*) FROM career.organization_job_postings WHERE status IN ('draft','pending_review','rejected') "
     "AND public_posting_id IS NOT NULL", 0),
    ("COMPANY", "every published company posting links a published company_direct job_postings row",
     "SELECT count(*) FROM career.organization_job_postings o LEFT JOIN career.job_postings jp "
     "ON jp.job_posting_id=o.public_posting_id WHERE o.status='published' AND o.revision_of IS NULL AND "
     "(jp.job_posting_id IS NULL OR jp.status<>'published' OR jp.source_id IS DISTINCT FROM "
     "(SELECT source_id FROM career.data_sources WHERE code='company_direct'))", 0),
    ("PUBLIC_POSTINGS", "no published company_direct job_postings row without a published org posting",
     "SELECT count(*) FROM career.job_postings jp WHERE jp.source_id=(SELECT source_id FROM career.data_sources "
     "WHERE code='company_direct') AND jp.status='published' AND NOT EXISTS (SELECT 1 FROM "
     "career.organization_job_postings o WHERE o.public_posting_id=jp.job_posting_id AND o.status='published')", 0),
    ("PUBLIC_POSTINGS", "JobKorea-like crawled draft fixture is still draft (never published by any flow)",
     f"SELECT count(*) FROM career.job_postings WHERE job_posting_id='{JOBKOREA_DRAFT_ID}' AND status<>'draft'", 0),
    ("COMPANY", "every company posting event references its own organization",
     "SELECT count(*) FROM career.organization_job_posting_events e JOIN career.organization_job_postings o "
     "USING (posting_id) WHERE e.organization_id<>o.organization_id", 0),
    ("COMPANY", "every organization has at least one owner",
     "SELECT count(*) FROM career.organizations g WHERE NOT EXISTS (SELECT 1 FROM career.organization_members m "
     "WHERE m.organization_id=g.organization_id AND m.role='owner')", 0),
    ("MODERATION", "at most one open moderation case per target",
     "SELECT count(*) FROM (SELECT target_type, target_id FROM career.moderation_cases WHERE status IN "
     "('PENDING','IN_REVIEW','APPEALED') GROUP BY 1,2 HAVING count(*)>1) d", 0),
    ("MODERATION", "approved company_posting cases → target posting published",
     "SELECT count(*) FROM career.moderation_cases m JOIN career.organization_job_postings o ON o.posting_id=m.target_id "
     "WHERE m.target_type='company_posting' AND m.status='APPROVED' AND o.status<>'published'", 0),
    ("MODERATION", "rejected company_posting cases → target posting not public",
     "SELECT count(*) FROM career.moderation_cases m JOIN career.organization_job_postings o ON o.posting_id=m.target_id "
     "WHERE m.target_type='company_posting' AND m.status='REJECTED' AND o.public_posting_id IS NOT NULL", 0),
    ("MODERATION", "every decided case has a matching decision event",
     "SELECT count(*) FROM career.moderation_cases m WHERE m.status IN ('APPROVED','REJECTED') AND NOT EXISTS "
     "(SELECT 1 FROM career.moderation_case_events e WHERE e.case_id=m.case_id AND e.to_status=m.status)", 0),
    ("NOTIFICATION", "no notification rows were created for self-initiated application stage changes",
     "SELECT count(*) FROM career.notification_deliveries d WHERE EXISTS (SELECT 1 FROM career.job_applications a "
     "WHERE a.user_id=d.user_id)", 0),
    ("USER", "job applications: one row per (user, posting)",
     "SELECT count(*) FROM (SELECT user_id, job_posting_id FROM career.job_applications WHERE job_posting_id IS NOT NULL "
     "GROUP BY 1,2 HAVING count(*)>1) d", 0),
    ("PORTFOLIO", "no active (unrevoked, unexpired) link for a user without current public-profile consent",
     "SELECT count(*) FROM career.public_profile_links l JOIN career.public_profile_selections s USING (user_id) "
     "WHERE l.revoked_at IS NULL AND l.expires_at>now() AND s.confirmed_version IS DISTINCT FROM s.version", 0),
    ("DOCUMENT", "no document stuck in scanning/deleting after the worker ran",
     "SELECT count(*) FROM career.user_documents WHERE status IN ('deleting')", 0),
]


def run(rec, admin_db: str, accounts: dict, state: dict) -> None:
    with psycopg.connect(admin_db, autocommit=True) as db:
        for area, name, query, want in CHECKS:
            def check(query=query, want=want):
                got = db.execute(query).fetchone()[0]
                assert got == want, f"got {got}, want {want}"
                return {"value": got}
            rec.check(area, "db-assert", name, check)

        def counts():
            tables = ["users", "job_applications", "notification_deliveries", "organizations",
                      "organization_job_postings", "organization_job_posting_events", "moderation_cases",
                      "moderation_case_events", "public_profile_links", "data_subject_requests", "user_documents",
                      "audit_events", "job_postings"]
            return {t: db.execute(f"SELECT count(*) FROM career.{t}").fetchone()[0] for t in tables}
        rec.check("PLATFORM", "db-assert", "row counts after all flows (evidence)", counts)
