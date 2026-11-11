-- PROPOSED (T96) — NOT a migration. database/migrate.py does not read this folder.
-- Purpose: 알림 발송 대기열(outbox)·발송 기록 (T95 계약 §4~§6). PM 승인 후 정식 번호 migration 으로 옮깁니다.
-- Recovery: 신규 표 1개만 추가하므로, 승인 전에는 적용하지 않습니다. 적용 후 문제 시 후속 migration 으로 표 제거(Destructive-Approval 필요).
-- 검증: backend/tests/test_t96_notifications_postgres.py 가 일회용 PostgreSQL 18 에만 적용합니다.
-- 저장하지 않는 것: 메일 본문, 링크·토큰, 수신 주소 원문(발송 시점에 users 에서 조회), 공급자 응답 원문.

CREATE TABLE career.notification_deliveries (
    delivery_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,   -- T87 분류: ANONYMIZE
    notification_type varchar(60) NOT NULL,
    channel varchar(16) NOT NULL DEFAULT 'email',
    status varchar(20) NOT NULL DEFAULT 'queued',
    attempts smallint NOT NULL DEFAULT 0,
    dedupe_key char(64) NOT NULL,
    template_code varchar(80) NOT NULL,
    template_version varchar(20) NOT NULL,
    variables jsonb NOT NULL DEFAULT '{}'::jsonb,                         -- 비밀이 아닌 템플릿 변수만
    last_error_code varchar(40),
    created_at timestamptz NOT NULL DEFAULT now(),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    locked_until timestamptz,
    sent_at timestamptz,
    PRIMARY KEY (delivery_id),
    CHECK (channel IN ('email', 'in_app')),
    CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'failed_permanent', 'cancelled')),
    CHECK (attempts BETWEEN 0 AND 10),
    CHECK (dedupe_key ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(variables) = 'object'),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
    CHECK ((status = 'sending') = (locked_until IS NOT NULL))
);

-- 같은 묶음 키는 처리 중(queued/sending) 행이 하나뿐 (동시 요청 최종 방어선)
CREATE UNIQUE INDEX notification_deliveries_active_dedupe
    ON career.notification_deliveries (dedupe_key) WHERE status IN ('queued', 'sending');
-- 중복 방지 창 조회
CREATE INDEX notification_deliveries_dedupe_recent
    ON career.notification_deliveries (dedupe_key, created_at DESC);
-- worker 가 꺼낼 대상
CREATE INDEX notification_deliveries_due
    ON career.notification_deliveries (next_attempt_at) WHERE status IN ('queued', 'sending');
-- 탈퇴(사용자 삭제) 시 SET NULL
CREATE INDEX notification_deliveries_user ON career.notification_deliveries (user_id);
-- 보존 기간 정리
CREATE INDEX notification_deliveries_created ON career.notification_deliveries (created_at);
