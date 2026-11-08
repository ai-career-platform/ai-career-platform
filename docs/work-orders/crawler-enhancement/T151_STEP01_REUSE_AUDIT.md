# T151 STEP 01 — 기존 구조 재사용 감사 및 최소 변경 설계

> Feature: Redmine #1578 (사용자 제공 번호; Redmine API 검증은 별도) · Task: T151 · 2026-11-08  
> 범위: GitHub `main` 정적 코드 분석. 로컬 PostgreSQL/Ubuntu 실행 상태는 미조회. 코드, DB, 배포, Timer는 변경하지 않음.

## 1. 결론

기존 T62/T63/T64 수집·정규화·UPSERT·Scheduler/Dispatcher를 재사용하고, **T151에서는 관리용 검색어 및 수집 계획/작업 상태만 최소 확장**한다. Raw HTML 저장은 T152, 파서 분리는 T153, 증분 체크포인트·21:00~08:00 시간창 및 실제 예약 실행은 T154, API/RBAC는 T155, UI는 T156의 책임이다.

## 2. 기존 코드 확인 결과

| 위치 | 확인된 기능 | T151 처리 |
| --- | --- | --- |
| `crawler/storage/migrations/0002_scheduler.sql` | `crawler_training.schedules`, `runs`, `run_events`; 단일 `jobkorea-daily` 스케줄, 기본 `enabled=false`, `mode=fixture` | 유지; 작업별 스케줄로 재설계 금지 |
| `crawler/jobs/scheduler.py` | T64 실행 가능 판정, DB claim/lock, heartbeat, 제한된 재시도, 일정 변경 | 재사용. 검색어 CRUD 책임을 섞지 않음 |
| `crawler/jobs/dispatcher.py` | 단발 실행, Worker subprocess, timeout, 실행 이력 CLI | 그대로 유지 |
| `crawler/jobs/run_crawler.py` | 합성 JobKorea Fixture 읽기, Normalizer/품질 게이트, 저장소 | 그대로 유지 |
| `crawler/storage/postgres.py` | `crawler_training.postings`의 `(source_code,external_posting_id)` 유니크 UPSERT | 그대로 유지; 발견 검색어는 별도 관계 |
| `crawler/jobs/import_jobkorea_html.py` | 수동 `--list-url` 기반 검색 목록 처리 예제 | T151에서 실사이트 호출/변경 없음 |
| `crawler/storage/migrations/0002_scheduler.sql` | Schedule이 `source_id` UNIQUE 및 1개 `jobkorea-daily` 중심 | 6개 검색어마다 기존 T64 schedule 레코드를 복제하지 말 것 |

`0001_initial.sql` 경로는 현재 확인되지 않았으므로 기존 `postings` 실 DB DDL은 별도 확인 필요.

## 3. T151 구현 계약 (제안)

### A. 검색어 6개 (별도 Config)

순서대로 `AI`, `Python`, `데이터 분석`, `LLM`, `업무 자동화`, `AI 엔지니어`. 고정 Python 상수로 실행 검색어를 관리하지 않고 격리 크롤러 DB의 Seed로 제공. 필드 예: `keyword_id`, `keyword`, `normalized_keyword`, `enabled`, `priority`, `created_at`, `updated_at`. 대소문자/중복·공백·유니코드 정규화 원칙 및 변경 이력 필요. 삭제는 기존 참조가 있으면 **비활성화(soft delete)** 우선; 하드 삭제로 기존 이력 소실 금지.

### B. 수집 작업 메타데이터

필드 후보: `job_id`, `keyword_id`, `run_id`(nullable, T64 연결 예정), `status`, `created_at`, `started_at`, `ended_at`, `attempt`, `error_code`, `idempotency_key`. T151 단계에서 네트워크 작업 예약/실행, T64 신규 Worker 시작까지 연결하지 말 것. 실행 상태는 T64 `runs.status`와 T151 관리 작업 상태를 구분하고 매핑표 작성.

### C. 검색어와 공고 발견 관계

`keyword_id`와 기존 `(source_code,external_posting_id)`를 기반으로 동일 공고가 여러 검색어에서 발견된 사실을 연결. 공고 본문을 검색어별 중복 저장하지 않는다. T151에서 관계 DDL/테스트를 먼저 만들되 실제 Fetch와 연결은 T152/T153에서 수행.

### D. Schema 변경

기존 앱 DB의 `career` 스키마와 기존 `crawler_training.postings/schedules/runs/run_events`는 변경하지 않는다. **신규 버전 Migration**을 분리하여 개발하고, `current_database() = ai_career_crawler_training` 확인, 새 테이블만 생성, 제약/인덱스/런타임 role 권한 최소화, 재실행/rollback 검증. 실제 스테이징 적용은 별도 Gate 이후.

## 4. 선행 실환경 READ-ONLY 확인 (Codex)

1. `crawler/storage/migrations` 전체 파일과 실제 `crawler_training` 테이블·인덱스·제약 확인.
2. 실제 스테이징 `ai_career_crawler_training` DB의 schedule `enabled=false,mode=fixture`, Timer disabled/inactive 확인.
3. 실제 `postings` 유니크 키·기존 행 수, `runs/run_events` 건수/컬럼 및 런타임 최소 권한 확인.
4. Secrets·원본 개인정보를 출력하지 않고, **DDL·신규 기능과 충돌 위험·추가 테이블 제안만** 요약.
5. 읽기 전용 이외 명령, migration 적용, Timer 조작, 크롤러 실행, 외부 HTTP, PR 작성/배포는 하지 않음.

## 5. T151 STEP 02 완료 목표

1. GitHub 전용 브랜치에서 격리 DB용 새 Migration/Seed(검색어 6개) + 검색어 CRUD 서비스(우선 내부 Python API) + 작업 메타데이터 모델/CRUD + 관계 및 멱등성 테스트.
2. 합성 Fixture 테스트와 GitHub CI PASS, 기존 T64 회귀 테스트 PASS.
3. `enabled=false` / Live HOLD 보장, 기존 서비스·실 DB untouched.
4. 이후 스테이징 Fixture E2E는 기존 Auto-CD 경로·영향 평가 후 수행.

## 6. 상태

`STEP01_CODE_AUDIT=PASS` (GitHub 코드 기준)  
`STAGING_DB_SCHEMA=NOT_VERIFIED`  
`LOCAL_DB_CHECK=NOT_RUN`  
`MIGRATION_APPLIED=NO`  
`PRODUCTION_CHANGED=NO`  
`LIVE_COLLECTION=HOLD`
