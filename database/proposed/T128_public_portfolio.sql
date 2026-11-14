-- PROPOSED (T128/T129) — NOT a migration. database/migrate.py does not read this folder.
-- Purpose: 공개 포트폴리오 공유 링크 저장소(backend/app/services/public_portfolio.py 의 MemoryPortfolioRepository 를
--          SQL 로 바꿀 때의 데이터 계약). 공개 항목 정책은 docs/enterprise/t128_public_profile_fields.json,
--          설계 설명은 docs/enterprise/T125_T128_DB_DESIGN.md.
--          공개 화면은 저장된 사본이 아니라 현재 프로필 데이터를 그린다(PP-INV-6) — 이 표들은 "무엇을 공개할지"만 담는다.
-- 의존: 0001~0003 만. T122(organizations)에 의존하지 않는다(기업 검색·목록 노출 없음, PP-INV-4).
-- 사전 데이터(승인 후 seed, 이 파일에 없음): career.consent_policies ('public_profile', <승인된 약관 버전>).
-- 기존 표 변경: user_experiences·user_projects 에 (user_id, id) UNIQUE 제약을 더한다(추가만, PK 가 이미 유일하므로
--          기존 데이터와 충돌 없음). 선택 항목이 반드시 본인 항목이도록 복합 FK 로 묶기 위함.
-- Recovery: 신규 표 4개 + UNIQUE 제약 2개. 승인 전 적용하지 않음. 적용 후 문제 시 후속 migration 으로 제거
--          (Destructive-Approval 필요). 표를 지우면 모든 공유 링크가 404 가 된다(공개 쪽으로 실패하지 않음).
-- 개인정보(전부 개인정보, T87 분류 DELETE):
--   - 모든 표가 user_id → career.users ON DELETE CASCADE. 탈퇴 즉시 선택·링크·동의 연결이 사라지고 링크는 404.
--   - 선택한 경력·프로젝트 행은 해당 항목 삭제 시 CASCADE(지운 항목은 즉시 공개 화면에서 사라짐).
--   - alias 는 사용자가 입력한 표시 이름. 링크 토큰은 원문을 저장하지 않고 SHA-256 해시(token_hash)만.
--   - 동의 기록은 기존 career.user_consents(policy_code='public_profile')에 남기고, 선택 버전만 보조 표에 둔다.
-- 검증: backend/tests/test_t125_t128_proposed_ddl_postgres.py (일회용 PG).

ALTER TABLE career.user_experiences ADD CONSTRAINT uq_user_experiences_owner UNIQUE (user_id, experience_id);
ALTER TABLE career.user_projects ADD CONSTRAINT uq_user_projects_owner UNIQUE (user_id, project_id);

-- 사용자별 공개 선택(Selection). 행이 없으면 Selection() — 아무것도 공개하지 않음(PP-INV-1).
CREATE TABLE career.public_profile_selections (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    fields text[] NOT NULL DEFAULT '{}',
    alias varchar(50),
    version integer NOT NULL DEFAULT 1,           -- 낙관적 잠금 + 동의 대상 버전
    confirmed_version integer,                    -- 미리보기 확인 후 동의한 버전. 선택이 바뀌면 NULL(PP-INV-7)
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id),
    CHECK (version >= 1),
    -- 공개 가능 항목만(PUBLISHABLE_FIELDS). email·documents·analysis_results 등 NEVER_PUBLIC 은 넣을 수 없다(PP-INV-2)
    CHECK (fields <@ ARRAY['display_name', 'headline', 'bio', 'location_text', 'experience.organization',
                           'experience.title', 'experience.period', 'experience.description', 'project.title',
                           'project.summary', 'project.period', 'skills', 'target_roles']::text[]),
    CHECK (cardinality(fields) <= 20),
    CHECK (alias IS NULL OR length(btrim(alias)) > 0),
    -- 동의는 현재 버전에만, 빈 선택에는 동의할 수 없다(consented = confirmed_version == version and fields)
    CHECK (confirmed_version IS NULL OR (confirmed_version = version AND cardinality(fields) > 0))
);

-- 항목별 선택(Selection.experience_ids / project_ids). 본인 항목만(복합 FK), 항목 삭제 시 함께 삭제.
CREATE TABLE career.public_profile_selected_experiences (
    user_id uuid NOT NULL REFERENCES career.public_profile_selections (user_id) ON DELETE CASCADE,
    experience_id uuid NOT NULL,
    PRIMARY KEY (user_id, experience_id),
    FOREIGN KEY (user_id, experience_id)
        REFERENCES career.user_experiences (user_id, experience_id) ON DELETE CASCADE
);
CREATE TABLE career.public_profile_selected_projects (
    user_id uuid NOT NULL REFERENCES career.public_profile_selections (user_id) ON DELETE CASCADE,
    project_id uuid NOT NULL,
    PRIMARY KEY (user_id, project_id),
    FOREIGN KEY (user_id, project_id)
        REFERENCES career.user_projects (user_id, project_id) ON DELETE CASCADE
);

-- 동의 기록 보조(MemoryPortfolioRepository.consents 의 selection_version). 동의·철회 본문은 career.user_consents 행.
CREATE TABLE career.public_profile_consent_records (
    consent_id uuid NOT NULL REFERENCES career.user_consents (consent_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    selection_version integer NOT NULL,
    PRIMARY KEY (consent_id),
    CHECK (selection_version >= 1)
);
CREATE INDEX ix_public_profile_consent_records_user ON career.public_profile_consent_records (user_id);

-- 공유 링크(ShareLink). 토큰 원문은 만들 때 한 번만 돌려주고 저장하지 않는다.
CREATE TABLE career.public_profile_links (
    link_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    token_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,                       -- 개별 회수 또는 동의 철회(전체 회수) 시각
    view_count integer NOT NULL DEFAULT 0,
    PRIMARY KEY (link_id),
    UNIQUE (token_hash),                          -- 공개 조회(view)는 이 유일 인덱스로 한 행만 찾는다
    CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '90 days'),   -- MAX_TTL
    CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CHECK (view_count >= 0)
);
-- 소유자 목록(links: created_at DESC)·활성 링크 수(MAX_ACTIVE_LINKS=3, 서비스가 선택 행 잠금 아래 검사)
CREATE INDEX ix_public_profile_links_user ON career.public_profile_links (user_id, created_at DESC);
CREATE INDEX ix_public_profile_links_active ON career.public_profile_links (user_id, expires_at) WHERE revoked_at IS NULL;
-- 만료·회수 링크 정리(제안 purge)
CREATE INDEX ix_public_profile_links_purge ON career.public_profile_links (expires_at);
