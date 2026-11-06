# S04 — AI Career Platform 전체 API 계약 v0.1

> 상태: **DRAFT / NOT IMPLEMENTED / NOT APPROVED** · 2026-11-06  
> 근거: [S02 기능·화면·API·DB 추적표](FULL_SCOPE_TRACEABILITY.md), [S03 전체 데이터 모델](../database/FULL_DATABASE_MODEL.md).  
> **주의:** `/api/v1` 아래 명시한 모든 경로는 설계 후보입니다. 현재 Staging에서 검증된 PoC 헬스/버전 엔드포인트와 구분합니다. 원본 Redmine·최종 화면/API 요구사항은 아직 미확인입니다.

## 1. 공통 HTTP/API 계약 후보

| 항목 | 제안 계약 | 최종 확정 필요 |
|---|---|---|
| Base path | `/api/v1` | API Gateway/Nginx 경로 |
| 전송 | HTTPS/TLS; JSON UTF-8; 문서 업로드에만 `multipart/form-data` | 외부 공개 라우팅 |
| 인증 | 비공개 API는 `Authorization: Bearer <access_token>` 후보 | OIDC/OAuth 외부 IdP vs 자체 인증, 토큰 발행·검증·갱신 방식 |
| 인가 | 엔드포인트별 scopes + 리소스 소유권(서버측). /admin 별도 권한 필수 | 서비스 사용자 역할 및 기업 관리자 범위 |
| 필터/정렬 | 허용 목록 기반 `sort`, `status`, `q`; 무제한 검색/정렬 금지 | API별 필터 허용 집합 |
| 페이지네이션 | `limit` 1~100 (기본 20), `cursor` 불투명 문자열. 정렬키 안정화 | 데이터 규모·실제 UI |
| 일시 | ISO 8601 timezone-aware, 저장 UTC `timestamptz` | 표시/사업 타임존 |
| 식별자 | UUID 문자열, `code`는 안정적인 직무·기술 식별 | 외부 IdP subject/API 공개 ID |
| 생성 | 성공 `201`, 가능하면 `Location`; 비동기 작업은 `202`와 조회 URL | 비동기 작업 큐 구축 |
| 수정 | `PATCH`은 명시 필드만 갱신, `PUT`은 대상 컬렉션 전체 교체로 정의 | PATCH 허용 필드, 낙관적 동시성 |
| 삭제 | `204` (본문 없음), 개인정보 삭제·보존은 별도 정책 적용 | soft/hard delete |
| 멱등 | 상태를 교체하는 PUT/DELETE, Seed; 결제·Agent 외부 부작용은 `Idempotency-Key` 후보 | 키 보존/중복 요청 처리 |
| 오류 | 통합 `application/problem+json` 후보, 민감한 내부 오류 비노출 | 기존 FastAPI/Pydantic 오류 422 래핑 방식 |
| OpenAPI | FastAPI `/openapi.json`, `/docs`는 접근 통제 후 사용 | 배포 시 노출 정책 |

**오류 상태 코드:** 400 업무 규칙/잘못된 상태, 401 인증 실패, 403 인가 실패, 404 리소스 없음(비소유자 정보 은닉에도 사용), 409 중복·상태 충돌, 413 파일 용량 초과, 415 파일 유형 미지원, 422 요청 필드 검증 실패, 429 요청 한도, 500 서버 오류, 502/503 AI 외부서비스·의존성 장애, 504 타임아웃. 이는 기본 규약이며 API별 상세 오류는 확정 전.

오류 응답 후보:

```json
{
  "type": "https://example.invalid/problems/validation",
  "title": "Validation Failed",
  "status": 422,
  "code": "VALIDATION_FAILED",
  "detail": "One or more request fields are invalid.",
  "request_id": "req-example-001",
  "errors": [
    {"field": "email", "code": "INVALID_FORMAT"}
  ]
}
```

※ `example.invalid`은 예시이며 실제 오류 문서 URL 아님. 이메일·토큰·이력서 텍스트·LLM 프롬프트·스택트레이스는 오류에 포함하지 않음.

목록 응답 후보:

```json
{
  "items": [
    {"id": "9f8e8f99-2a67-49ca-96ab-4aa3e4db83c0", "name": "Backend Engineer"}
  ],
  "next_cursor": null
}
```

## 2. 기능 단위 전체 API 목록 — F-001~F-030

`A`=인증 필요, `P`=인증 없이 접근 후보, `M`=운영 관리자 권한, `O`=리소스 소유권 필수. `X`=인증 정책 미확정.
각 항목의 Request/Response는 **핵심 DTO 필드 초안**만 표시한 것으로 상세 JSON Schema와 검증은 구현 전 별도 확정한다.

### A. 계정·인증·프로필 (F-001~F-005)

| ID / UI | Method + Endpoint 제안 | 권한 | Request 후보 → Response 후보 | DB 후보 | 주요 상태 |
|---|---|---|---|---|---|
| F-001 / UI-001 | `POST /auth/login` | X | `provider?,credential?` → `access_token,expires_in` (자체 인증일 때만) | users, auth_identities | 200/401/429 |
| F-001 / UI-001 | `GET /auth/callback` | X | `code,state` → 세션/리디렉션 (IdP 경우) | auth_identities, auth_sessions? | 302/400 |
| F-002 / UI-002 | `POST /auth/logout` | A | session token → empty | auth_sessions? | 204/401 |
| F-003 / UI-003 | `GET /me` | A,O | — → `user_id,email,display_name,profile` | users, user_profiles | 200/401 |
| F-003 / UI-003 | `PATCH /me` | A,O | `display_name?,headline?,bio?,location_text?` → `UserProfileDto` | users, user_profiles | 200/409/422 |
| F-004 / UI-004 | `GET /me/permissions` | A | — → `roles[],permissions[]` | roles, permissions, user_roles, role_permissions | 200/401 |
| F-005 / UI-005 | `GET /me/consents` | A,O | — → `ConsentDto[]` | user_consents | 200/401 |
| F-005 / UI-005 | `POST /me/consents` | A,O | `policy_code,policy_version,granted` → `ConsentDto` | user_consents | 201/409/422 |
| F-005 / UI-005 | `POST /me/deletion-requests` | A,O | `confirmation` → `request_id,status` | **삭제 요청 테이블 S03에 누락** | 202/409 |

**설계 미결정:** 외부 IdP를 쓸 경우 로그인/콜백/로그아웃 URI와 자체 토큰 DTO의 형태가 크게 달라진다. **비밀번호 자체 저장/발급·refresh 로직을 임의로 구현하지 말 것**. 위 로그인 두 경로는 **서로 다른 인증 방식의 후보**, 동시 구현 필수가 아니다.

### B. 역량·직무·경력 (F-006~F-010, F-014)

| ID / UI | Method + Endpoint 제안 | 권한 | Request → Response | DB 후보 | 상태 |
|---|---|---|---|---|---|
| F-006 / UI-006 | `GET /job-roles` | P/A | `q,limit,cursor` → `JobRoleDto[]` + cursor | job_roles | 200 |
| F-006 / UI-006 | `GET /job-roles/{job_role_id}` | P/A | — → `JobRoleDto` | job_roles | 200/404 |
| F-007 / UI-007 | `GET /skills` | P/A | `q,limit,cursor` → `SkillDto[]` + cursor | skills | 200 |
| F-008 / UI-008 | `GET /me/skills` | A,O | — → `UserSkillDto[]` | user_skills | 200 |
| F-008 / UI-008 | `PUT /me/skills` | A,O | `items[{skill_id,proficiency?}]` → `UserSkillDto[]` | user_skills | 200/409/422 |
| F-009 / UI-009 | `GET /me/target-roles` | A,O | — → `TargetRoleDto[]` | user_target_roles | 200 |
| F-009 / UI-009 | `PUT /me/target-roles` | A,O | `items[{job_role_id,priority?}]` → `TargetRoleDto[]` | user_target_roles | 200/422 |
| F-010 / UI-010 | `GET /me/experiences` | A,O | — → `ExperienceDto[]` | user_experiences | 200 |
| F-010 / UI-010 | `POST /me/experiences` | A,O | `organization,title,start_date?,end_date?` → `ExperienceDto` | user_experiences | 201/422 |
| F-010 / UI-010 | `PATCH /me/experiences/{experience_id}` | A,O | partial `ExperienceDto` → `ExperienceDto` | user_experiences | 200/404/422 |
| F-010 / UI-010 | `GET/POST /me/projects` | A,O | project DTOs → `ProjectDto`/list | user_projects | 200/201 |
| F-014 / UI-014 | `GET /job-roles/{job_role_id}/skills` | P/A | — → `RoleSkillDto[]` | job_role_skills | 200/404 |
| F-014 / UI-014 | `GET /job-postings/{job_posting_id}/skills` | P/A | — → `PostingSkillDto[]` | job_posting_skills | 200/404 |

### C. 기업·공고 (F-011~F-013)

| ID / UI | Method + Endpoint 제안 | 권한 | Request → Response | DB 후보 | 상태 |
|---|---|---|---|---|---|
| F-011 / UI-011 | `GET /companies` | P/A | `q,limit,cursor` → company list | companies | 200 |
| F-011 / UI-011 | `GET /companies/{company_id}` | P/A | — → `CompanyDto` | companies | 200/404 |
| F-012 / UI-012 | `GET /job-postings` | P/A | `q,company_id,job_role_id,status,sort,limit,cursor` → posting list | job_postings | 200/422 |
| F-012 / UI-012 | `GET /job-postings/{job_posting_id}` | P/A | — → `JobPostingDto` | job_postings | 200/404 |
| F-013 / UI-013 | `GET /me/bookmarks` | A,O | cursor → bookmarked postings | user_job_bookmarks | 200 |
| F-013 / UI-013 | `PUT /me/bookmarks/{job_posting_id}` | A,O | — → no content | user_job_bookmarks | 204/404 |
| F-013 / UI-013 | `DELETE /me/bookmarks/{job_posting_id}` | A,O | — → no content | user_job_bookmarks | 204/404 |

외부 공고 수집 API는 일반 사용자 API에 포함하지 않고 승인된 백그라운드 작업·관리자 경로로 분리한다. 외부 데이터 권한·중복·삭제 정책 미확정.

### D. 직무 매칭·Skill Gap·추천 (F-015~F-018)

| ID / UI | Method + Endpoint 제안 | 권한 | Request → Response | DB 후보 | 상태 |
|---|---|---|---|---|---|
| F-015 / UI-015 | `POST /matches/evaluate` | A,O | `job_posting_id? / job_role_id?` → `match_id,score?,model_version?,limitations[]` | match_evaluations, model_versions | 200/202/422/503 |
| F-015 / UI-015 | `GET /matches/{match_id}` | A,O | — → `MatchEvaluationDto` | match_evaluations | 200/404 |
| F-016 / UI-016 | `POST /skill-gaps/analyze` | A,O | `job_role_id` → `assessment_id,items[]` | skill_gap_assessments/items | 200/202/422 |
| F-016 / UI-016 | `GET /skill-gaps/{assessment_id}` | A,O | — → gap assessment result | skill_gap_assessments/items | 200/404 |
| F-017 / UI-017 | `GET /recommendations/jobs` | A,O | `limit,cursor` → `run_id,items[{job_posting_id,rank,score?,reason?}]` | recommendation_runs/items | 200/202/503 |
| F-018 / UI-018 | `GET /recommendations/{run_id}` | A,O | — → `RecommendationRunDto` | recommendation_runs/items | 200/404 |
| F-018 / UI-018 | `POST /recommendations/{run_id}/feedback` | A,O | `job_posting_id,feedback` → `feedback_id,status` | **feedback 이력 테이블 S03 누락** | 201/409/422 |

**설명 규칙:** 추천·매칭 점수를 채용 성공 확률로 해석하지 않으며 결과에는 모델 버전, 데이터 기간, 한계/불확실성 또는 설명 가능 범위를 제공할 수 있어야 한다. 모델 호출 실패 시 핵심 목록/프로필 API가 중단되지 않도록 격리한다.

### E. 문서·LLM·RAG·Agent (F-019~F-023)

| ID / UI | Method + Endpoint 제안 | 권한 | Request → Response | DB 후보 | 상태 |
|---|---|---|---|---|---|
| F-019 / UI-019 | `POST /documents` | A,O | `multipart/form-data file,kind` → `document_id,status` | user_documents | 201/413/415 |
| F-019 / UI-019 | `GET /documents` | A,O | cursor → owner document list | user_documents | 200 |
| F-019 / UI-019 | `DELETE /documents/{document_id}` | A,O | — → no content or deletion job | user_documents + object storage/index | 204/202/404 |
| F-020 / UI-020 | `POST /document-analyses` | A,O | `document_id,analysis_type` → `analysis_id,status` | document_analyses | 202/422 |
| F-020 / UI-020 | `GET /document-analyses/{analysis_id}` | A,O | — → `AnalysisDto` | document_analyses | 200/404 |
| F-021 / UI-021 | `POST /knowledge/search` | A | `query,filters?,limit` → `matches[{chunk_id,document_id,score?,source}]` | document_chunks, retrieval_runs/citations | 200/403/422 |
| F-022 / UI-022 | `POST /knowledge/answer` | A | `query,filters?` → `answer,run_id,citations[],limitations[]` | retrieval_runs/citations, documents | 200/202/503 |
| F-023 / UI-023 | `POST /agent-runs` | A | `workflow_code,input_ref?,idempotency_key?` → `agent_run_id,status` | agent_runs | 202/403/429 |
| F-023 / UI-023 | `GET /agent-runs/{agent_run_id}` | A,O | — → `AgentRunDto` | agent_runs/tool_calls | 200/404 |
| F-023 / UI-023 | `POST /agent-runs/{agent_run_id}/approvals/{approval_id}` | A,owner/approver | `decision,reason?` → `ApprovalDto` | agent_tool_approvals | 200/403/409 |

**보안 필수:** 업로드 MIME + 실제 파일 시그니처 검사, 크기 제한, 악성 파일 검사, 객체 저장소 ACL, RAG 원본문서의 권한 상속, prompt injection 대비 및 외부 Tool 부작용 승인. API 권한 없이는 문서·청크·Agent 실행 결과나 인용 근거가 노출되면 안 됨.

### F. ML·시장·관리·운영 (F-024~F-030)

| ID / UI | Method + Endpoint 제안 | 권한 | Request → Response | DB 후보 | 상태 |
|---|---|---|---|---|---|
| F-024 / UI-024 | `GET /market-trends` | A 또는 P | `job_role_id?,metric_code,from,to` → `observations[],forecasts[],source` | market_observations/forecasts | 200/422 |
| F-025 / UI-025 | `GET /insights` | A,권한 범위 | `segment?,period?` → `aggregates[],limitations[]` | behavior_events, user_segments, anomaly_events | 200/403 |
| F-026 / UI-026 | `GET /admin/models` | M | `limit,cursor` → `ModelVersionDto[]` | model_versions, model_evaluations | 200/403 |
| F-026 / UI-026 | `GET /admin/models/{model_version_id}/evaluations` | M | — → metrics/evaluation references | model_evaluations | 200/403/404 |
| F-027 / UI-027 | `GET /admin/reviews` | M | `status,limit,cursor` → review items | **moderation_reviews 테이블 S03에 없음** | 200/403 |
| F-027 / UI-027 | `POST /admin/reviews/{review_id}/decision` | M | `decision,reason` → review status | **moderation_reviews 테이블 S03에 없음** | 200/403/409 |
| F-028 / UI-028 | `GET /admin/audit` | M | time range, actor, action → audit events | audit_events | 200/403 |
| F-028 / UI-028 | `GET /admin/ai-usage` | M | time range, model → usage totals | ai_usage_records | 200/403 |
| F-029 / 없음 | 관리자 승인된 DB migration/seed CLI | OS/DB 역할 | **Public HTTP API 없음** | migration ledger + seed revision | 별도 Runbook |
| F-030 / 없음 | `GET /api/health`, `GET /api/version` | 내부/PoC 정책 | 현재 Staging PoC 기존 경로 | 시스템 상태 | 기존 동작 유지 |

## 3. 대표 DTO 상세 (초안, Pydantic v2 대응 계획)

| DTO | 주요 필드·타입 후보 | 검증/데이터 소유권 |
|---|---|---|
| `UserDto` | `user_id: UUID`, `email: EmailStr`, `display_name: str(1..100)`, `status: Literal[active,disabled]` | 이메일은 본인·관리자에게만, 비밀번호/해시는 응답 절대 금지 |
| `UserProfilePatch` | `display_name?: str`, `headline?: str`, `bio?: str`, `location_text?: str` | omitted vs null 구분; null 허용 필드는 제한 |
| `SkillDto` | `skill_id: UUID`, `code: str`, `name: str` | 기준 코드 정규화·출처 |
| `UserSkillDto` | `skill_id: UUID`, `proficiency: int[1..5] | null` | user_id는 토큰에서; 클라이언트 입력 user_id 무시 |
| `JobPostingDto` | `job_posting_id: UUID`, `company_id: UUID`, `job_role_id?: UUID`, `title: str`, `status: str`, `published_at?: datetime` | 비공개 공고 노출 금지 |
| `MatchEvaluateRequest` | `job_posting_id?: UUID`, `job_role_id?: UUID` | 둘 중 하나 정확히 한 개 지정하는 정책 **제안** |
| `MatchEvaluationDto` | `match_id: UUID`, `score?: Decimal`, `model_version?: str`, `limitations: list[str]` | 점수 의미·범위/평가 기간과 공정성 지표 문서화 |
| `SkillGapDto` | `assessment_id: UUID`, `job_role_id: UUID`, `items: list[GapItemDto]` | 소유자 아닌 사용자 데이터 접근 금지 |
| `DocumentDto` | `document_id: UUID`, `kind: str`, `status: str`, `checksum?: str` | 저장 키·파일 내부 위치·원본 경로 공개 금지 |
| `RagAnswerDto` | `run_id: UUID`, `answer: str`, `citations: list[CitationDto]`, `limitations: list[str]` | 인용은 권한 검증된 문서/Chunk만 |
| `AgentRunDto` | `agent_run_id: UUID`, `status: str`, `tool_calls_summary?: list` | 승인되지 않은 Tool 실행 금지 |

**주의:** 위 표는 구현을 위한 필드 방향이지 완전한 JSON Schema/OpenAPI가 아닙니다. 필수값/nullable/default, enum 코드, 숫자 단위, URL 규칙, 배열 크기, 성능 SLA는 요구사항 확정 후 기계적으로 검증 가능한 OpenAPI 3.1로 내려야 합니다.

### 예시 — Skill Gap 요청

```json
{
  "job_role_id": "f61d17ab-f239-4991-a979-887b3b4ccaf1"
}
```

### 예시 — Skill Gap 응답

```json
{
  "assessment_id": "02a33aa5-d58c-4bc5-bb8e-62e8f45c53f5",
  "job_role_id": "f61d17ab-f239-4991-a979-887b3b4ccaf1",
  "items": [
    {
      "skill_id": "b6ced581-5b80-42fe-ab6b-4f0eedf7206e",
      "required_level": 4,
      "observed_level": 2,
      "gap": 2
    }
  ]
}
```

## 4. S03 데이터 모델과 교차 검토 — 누락/충돌

| 항목 | 발견된 차이 | 후속 조치 |
|---|---|---|
| F-005 계정 삭제 요청 | `deletion_requests` 테이블 부재 | 탈퇴/보존 정책 확정 후 S03 반영 |
| F-018 추천 피드백 | S03 `recommendation_items.feedback` 단일 값만 존재 | 피드백 이력·작성 시각/행위자 필요 시 별도 엔터티 |
| F-027 관리자 검수 | `moderation_reviews` 같은 검수 엔터티 없음 | 실제 콘텐츠 검수 요구사항 확인 후 모델 추가 |
| F-001 로그인 | 자체 토큰 로그인과 외부 OIDC 콜백 경로가 혼재 | 인증 방식 선택 후 불필요 경로 제거 |
| F-023 Agent 승인 | 승인 요청/실행 소유권 및 승인자 역할 정책 미정 | 승인 권한/재사용·취소·감사 API 계약 |
| F-021~022 RAG | `document_chunks` 참조만으로 권한 경계가 충분하지 않음 | 사용자·팀·기업별 접근 통제 및 인용 검증 정책 |
| F-024 시장 분석 | 소스/모델 데이터 사용권한·수집 기간 미정 | external data contract 및 품질 검사 |
| F-029 운영 migration | 공개 HTTP API 없어야 함 | GitHub + 수동 승인 + CLI로 운영 |

**정합성 검토 결론:** S04의 설계 후보는 S03와 연결 가능하지만, 위 **3개 기능(탈퇴 요청·추천 피드백·검수)의 엔터티 누락**과 인증·권한 정책 미확정으로 `S03_S04_CONSISTENCY=PARTIAL`. 이슈를 가리고 PASS 판정하지 않음.

## 5. API 구현을 위한 테스트 계약 (공통)

- 정상(200/201/202/204), 미인증(401), 비인가(403/404), 없는 리소스(404), 중복(409), 값 검증(422), 경계값과 페이징(400/422).
- 사용자 A가 사용자 B의 프로필/문서/추천/Agent 내역에 접근 시 차단. 클라이언트가 임의 사용자 ID를 보내도 서버에서 인증 주체를 기준으로 제한.
- 공고 목록의 필터·정렬·커서가 결정적이며 중복·누락 없음. 임의 정렬 SQL 삽입/쿼리 대량 반환 금지.
- AI 외부 API timeout/실패/쿼터·비용 초과 시 429/503/504 등 명시적 오류 또는 대체 응답. 데이터 복제/권한 누출 없음.
- 문서 업로드의 용량·확장자/MIME·실제 시그니처 검사, 소유자와 RAG 인덱스/삭제 일관성 검증.
- 모델 결과에는 모델 버전/평가지표/해석 한계, 훈련·검증 누수 방지, 추천 근거/편향 점검.
- 모든 API는 FastAPI Swagger Evidence, pytest, CI와 Staging 검증을 연결. DB 변경은 별도 승인 절차.

## 6. 계획된 구현 순서와 승인 조건

1. **S04 DRAFT:** 이 문서의 전 영역 엔드포인트·DTO·오류·권한 초안 작성. 구현 상태로 간주하지 않음.
2. **Contract Gate:** 전체 화면 목록·사용자 역할·IdP/자체 인증·기업/공고 데이터 사용 정책을 먼저 확인.
3. **S03/S04 Sync:** 누락 엔터티·경로·상태 코드/DTO를 정리하여 일관된 설계 베이스라인 수립.
4. **OpenAPI Contract:** `openapi.yaml` 또는 FastAPI Pydantic 스키마를 생성하고 자동 검사(참조/상태/필수필드/문법) 및 Mock API 검증.
5. **Incremental implementation:** 기존 Docker PoC와 분리된 `backend/frontend` 애플리케이션 코드 생성 후 Vertical Slice 단위 기능 구현.
6. **Integration:** DB migration/seed/권한 검증, CI E2E, 실제 Staging /api/health와 기존 자동 배포 보존 확인.

**상태:** `S04_API_CONTRACT_DRAFT=COMPLETE` / `OPENAPI_EXECUTABLE_SPEC=NOT_STARTED` / `REQUIREMENTS_APPROVAL=PENDING` / `STAGING_DB_UNCHANGED`.
