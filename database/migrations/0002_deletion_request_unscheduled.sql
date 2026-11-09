-- Purpose: Record T31 deletion requests without inventing an unapproved purge date.
-- Recovery: Keep nullable dates until policy approval; restore NOT NULL only after
-- Recovery: all unknown dates are resolved under an approved corrective migration.
-- Source: T31 implementation; D-06 thirty-day retention remains a draft.
ALTER TABLE career.account_deletion_requests
    ALTER COLUMN scheduled_purge_at DROP NOT NULL;
