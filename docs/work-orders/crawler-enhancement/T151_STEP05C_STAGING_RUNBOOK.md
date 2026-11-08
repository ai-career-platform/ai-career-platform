# T151 STEP 05C — 스테이징 수동 Migration + Fixture 검증 실행 계약

> 목표: 기존 서비스·DB 기록을 보존하며 `0003_keywords_jobs.sql`, `0004_keyword_audit.sql`만 스테이징 전용 크롤러 DB에 순서대로 적용하고 확인.

## 사전 상태와 게이트

1. `main` 및 staging 배포 SHA 일치 여부 확인. 이 문서가 작성된 시점의 기존 SHA는 `eef81573411ab4fb3fd5e8778fa66079de2aaf52`. 문서 PR 병합 이후 SHA가 변경될 수 있으니 실제 적용 직전 재확인.
2. 원본 크롤러 DB명 `ai_career_crawler_training` 확인. 앱 DB 접속 시 즉시 중단.
3. 기존 crawler 4개 테이블 행 수 `7/1/1/3`, `postings` 지문 `e842f12aec1cde3804813074c64a5080`, 기존 51개 앱 테이블 보존 확인.
4. 기존 스케줄 `enabled=false,mode=fixture`; Timer disabled/inactive; Live HOLD.
5. 최근 원본 백업 파일의 존재·체크섬 확인(`a2840beae219caf4050e172f1de88aad5b9eee31872fd1f3862979dd5f1ce0c0`). 독립 restore PASS 기록과 백업 안전 보존 확인. 파일 누락/해시 불일치/새 데이터 발생 시 **적용 중단, 새로운 백업·복원 검증부터**.
6. 기존 `0003`/`0004` 테이블 적용 여부 재조회. 예상외 사전 적용 또는 스키마 불일치 시 변경 중단.
7. Migration 실행자는 **승인된 제한적 schema-owner/관리자**로 실행하고 기존 runtime 계정에 CREATE 권한을 새로 부여하지 않는다.

## 스테이징 변경 (범위 한정)

- 기존 코드 `crawler/storage/migrations/0003_keywords_jobs.sql` 먼저 1회 적용.
- 성공 확인 후 `crawler/storage/migrations/0004_keyword_audit.sql` 적용.
- 각 SQL 자체의 `BEGIN/COMMIT`, 대상 DB명 검증을 그대로 사용. `psql -v ON_ERROR_STOP=1` 등 실패 시 즉시 중단되는 절차.
- `0003`: 신규 `search_keywords`, `keyword_jobs`, `keyword_posting_discoveries` 및 6개 Seed.
- `0004`: 신규 `keyword_audit_events`.
- 기존 `postings/schedules/runs/run_events` 및 앱 51개 테이블에 ALTER/UPDATE/DELETE 하지 않음.
- 두 스크립트 중 하나가 실패하면 **중단**하고 현재 상태와 실패한 SQL만 보고. 즉시 전체 DB를 복원하거나 사후 migration을 무조건 재시도하지 않는다. 필요 시 검증된 백업으로 복원하는 별도 복구 지시를 받는다.

## 검증

1. 4개 신규 테이블, 인덱스, PK/FK/Unique, 기본 키워드 6개(`AI`, `Python`, `데이터 분석`, `LLM`, `업무 자동화`, `AI 엔지니어`) 확인.
2. 기존 4개 테이블 행 수와 지문·T64 상태가 사전 스냅샷과 동일한지 확인.
3. 비소유 runtime 계정 최소 SELECT/INSERT/UPDATE 기능 및 CREATE/DROP 권한 미부여 확인.
4. **Fixture smoke**: 신규 메타데이터에 한정해 등록/수정/활성화·비활성화/soft delete/작업 멱등성/감사 이벤트/공고 발견 관계 검증. 가능하면 검증용 DB 트랜잭션을 롤백하여 원본 게시물 7건 및 6개 Seed가 변경되지 않도록 한다. 실제 Scheduler claim, 외부 요청 및 live worker 실행 금지.
5. 감사 이력: 초기 Seed는 개별 CREATE 감사 이력이 없고, KeywordStore를 통한 변경부터 기록되는 설계를 반영.
6. 기존 앱 서비스 health, Auto-CD, Timer status 및 크롤러 scheduler `enabled=false,mode=fixture` 재확인.
7. **실제 Fixture E2E를 수행하지 못한 경우** `STAGING_FIXTURE_E2E=HOLD`로 명시하며 메타데이터 스모크 PASS와 구분한다.

## 금지 및 보존

- LIVE 크롤링/외부 사이트 HTTP 요청, Timer 활성화, Schedule enabled=true 변경, 컨테이너 재시작/배포 변경 금지.
- 기존 게시물 7건과 T64 schedules/runs/run_events를 수정하지 않음.
- 기존 백업 삭제/덮어쓰기 금지. 과거 테스트 클러스터 데이터 폴더 삭제 정책 우회 금지.
- 시크릿/개인정보/원본 DB dump GitHub 업로드 금지.

## 출력

```
FEATURE=1578
TASK=T151
STEP=05C
MAIN_SHA=
STAGING_SHA=
BACKUP_SHA256_RECHECK=
MIGRATION_0003=
MIGRATION_0004=
NEW_TABLES_COUNT=
SEED_KEYWORDS=
KEYWORD_CRUD_SMOKE=
AUDIT_SMOKE=
JOB_IDEMPOTENCY_SMOKE=
POSTING_DISCOVERY_SMOKE=
EXISTING_TABLES_COUNTS_BEFORE=
EXISTING_TABLES_COUNTS_AFTER=
POSTINGS_FINGERPRINT_BEFORE=
POSTINGS_FINGERPRINT_AFTER=
APP_DB_PRESERVED=
SCHEDULER_ENABLED=
SCHEDULER_MODE=
TIMER_STATUS=
STAGING_FIXTURE_E2E=
LIVE_COLLECTION=HOLD
RESULT=PASS/HOLD/FAIL
BLOCKERS=
```
