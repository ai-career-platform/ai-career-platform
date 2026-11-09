# T151 STEP 02 — 검색어/작업 메타데이터 구현

## 구성
- `crawler/storage/migrations/0003_keywords_jobs.sql`: 격리된 `ai_career_crawler_training`에 **수동 적용**할 3개 테이블 및 검색어 6개 Seed.
- `crawler/jobs/keyword_management.py`: 내부 Python 검색어 CRUD, soft-delete, 작업 메타데이터 멱등 생성 및 상태전이, 검색어↔공고 관계 기록. FastAPI/실제 큐 연결 없음.
- `crawler/tests/test_t151_keywords.py`: DB/HTTP 없는 순수 로컬 계약 테스트.

## 주요 원칙
기존 `postings/schedules/runs/run_events` 테이블을 변경하지 않으며, 실제 스테이징 Migration 적용과 예약 실행은 별도 단계. 소프트 삭제는 과거 발견관계 보존을 위한 정책. 동일 idempotency_key 다른 검색어 사용은 오류. PostgreSQL Unique/FK 제약으로 일관성 보강.

## 검증
`python -m unittest crawler.tests.test_t151_keywords -v`
`python -m unittest discover -s crawler/tests -v`

## Staging 적용 전 체크
1. 기존 DB 스키마·행 수 백업 및 migration dry-run/rollback 검증.
2. DB role 권한 및 기존 읽기 전용 서비스 영향 확인.
3. 기존 `enabled=false`, `mode=fixture`, systemd Timer disabled/inactive를 변경하지 않음.
4. T151 테스트와 T64 회귀 PASS + PR CI PASS 후 별도 Fixture E2E 진행.

## 상태
Code: IMPLEMENTED ON FEATURE BRANCH; CI/STAGING 미확인. Live collection: HOLD. Redmine 상위 Feature #1578.
