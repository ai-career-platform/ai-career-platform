-- Purpose: T96 알림 발송 대기열(outbox)·발송 기록 + T97 화면 내 알림함 읽음 상태 + 사용자 수신 설정 (T95 계약 §2·§3·§6).
--          계약: docs/notifications/T95_NOTIFICATION_CONTRACT.md, T96_NOTIFICATION_DISPATCH.md, docs/testing/T97_NOTIFICATION_UI_VALIDATION.md.
--          API(T97 알림함·수신 설정)는 NOTIFICATIONS_API=true 일 때만 열림. 발송 worker 기본 공급자는 여전히 미설정(발송 없음).
-- Recovery: 신규 표 2개·인덱스만 추가(기존 표·데이터 변경 없음). 실패 시 러너가 롤백.
--           적용 후 제거는 후속 migration(Destructive-Approval 필요)으로만 한다.
-- 개인정보: notification_deliveries.user_id ON DELETE SET NULL(T87 분류 ANONYMIZE), notification_preferences.user_id
--           ON DELETE CASCADE(DELETE). 저장하지 않는 것: 메일 본문, 링크·토큰, 수신 주소 원문, 공급자 응답 원문.
-- 운영(GCP) 적용은 #344 절차와 별도 PM 승인 후에만 한다.
-- 검증: backend/tests/test_t96_notifications_postgres.py, backend/tests/test_t97_notifications_api_postgres.py (일회용 PostgreSQL 18).

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
    read_at timestamptz,                                                  -- T97: 알림함에서 읽은 시각(in_app·sent 만)
    PRIMARY KEY (delivery_id),
    CHECK (channel IN ('email', 'in_app')),
    CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'failed_permanent', 'cancelled')),
    CHECK (attempts BETWEEN 0 AND 10),
    CHECK (dedupe_key ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(variables) = 'object'),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
    CHECK ((status = 'sending') = (locked_until IS NOT NULL)),
    CHECK (read_at IS NULL OR (channel = 'in_app' AND status = 'sent'))
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
-- T97 알림함: 본인 in_app 알림 최신 순 / 안 읽음 개수
CREATE INDEX notification_deliveries_inbox
    ON career.notification_deliveries (user_id, created_at DESC, delivery_id DESC)
    WHERE channel = 'in_app' AND status = 'sent';
CREATE INDEX notification_deliveries_inbox_unread
    ON career.notification_deliveries (user_id)
    WHERE channel = 'in_app' AND status = 'sent' AND read_at IS NULL;

-- T97 수신 설정: 선택 알림(유형·채널)별 사용자 선택. 행이 없으면 T95 매트릭스 기본값.
-- 필수 알림은 행을 만들지 않는다(API 가 422 로 거부). 동의 이력(user_consents) 연동은 T95 동의 코드 승인 후.
CREATE TABLE career.notification_preferences (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,   -- T87 분류: DELETE
    notification_type varchar(60) NOT NULL,
    channel varchar(16) NOT NULL DEFAULT 'email',
    enabled boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, notification_type, channel),
    CHECK (channel IN ('email', 'in_app')),
    CHECK (notification_type ~ '^[a-z]+\.[a-z_]+$')
);

COMMENT ON TABLE career.notification_deliveries IS 'T96 알림 발송 대기열·기록(본문·링크·주소 원문 저장 안 함). in_app 행의 read_at 은 T97 알림함 읽음 상태';
COMMENT ON TABLE career.notification_preferences IS 'T97 사용자 선택 알림 수신 설정(행 없음 = T95 기본값). 필수 알림은 저장하지 않음';

-- 앱 역할 권한(역할이 있는 환경에서만). 기본 권한(DRAFT_00)이 없는 환경(GCP 등)도 같은 결과가 되도록 명시한다.
DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.notification_deliveries TO career_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.notification_preferences TO career_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN
        GRANT SELECT ON career.notification_deliveries TO career_reader;
        GRANT SELECT ON career.notification_preferences TO career_reader;
    END IF;
END
$grants$;
