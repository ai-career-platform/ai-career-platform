# T09 전체 DB 스키마 생성 SQL 작업 계획

- Redmine: [#1522](https://sulfite-footbath-next.ngrok-free.dev/issues/1522)
- 우선순위: P0
- 선행 일감: T05 전체 DB ERD 및 테이블 계약 확정, T08 PostgreSQL 마이그레이션 체계 구축
- 현재 구현 상태: NOT_STARTED

## 구현/변경 내용

### 승인 전 준비

1. Windows 로컬의 PostgreSQL 18.1 컨테이너에서 `pg_isready`로 DB 응답을 확인한다. 이미지 다운로드와 컨테이너 생성은 확인했으며, DB 응답과 초안 적용 결과는 확인 후 기록한다.
2. [DB 개발환경 가이드](development/DB_DEVELOPMENT_SETUP.md)에 따라 격리 DB에 `DRAFT_00_create_roles_schema.sql`과 `DRAFT_0001_initial_schema.sql`을 순서대로 적용한다. `career` 스키마의 기본 테이블 10개를 초안 재현의 기대값으로 사용한다.
3. [전체 DB 모델](../database/FULL_DATABASE_MODEL.md), [기능 추적표](FULL_SCOPE_TRACEABILITY.md), [API 계약](API_CONTRACT.md), 기존 마이그레이션을 비교하고 미확정 항목을 정리한다.

### 승인 후 구현

1. [T05 검토 PR](https://github.com/ai-career-platform/ai-career-platform/pull/17)의 승인된 ERD·데이터 사전 커밋과 T08의 파일 번호·적용 순서를 확인한다. 기존 초안과의 적용 관계도 T08 기준으로 확정한다.
2. 승인된 엔터티, 컬럼 타입, NULL 허용, 기본값, PK·FK와 삭제 동작, UNIQUE·CHECK·인덱스를 목록으로 정리한다.
3. 개인 브랜치에서 `database/migrations/<승인번호>.sql`을 작성한다. FK 의존성을 기준으로 테이블 생성 순서를 정하고 제약조건과 인덱스를 검토한다.

## 영향 범위

- 산출물은 독립 마이그레이션 SQL과 schema diff 리포트다. T10 Seed와 T11 제약 검증의 기준으로 공유한다.
- 실행 검증은 격리 PostgreSQL에서 진행한다. 공유 Staging 적용은 별도 승인 절차를 따른다.

## 검증 및 완료 기준

- 빈 격리 DB에서 T08의 승인 순서로 적용하고, 첫 오류에서 중단하도록 `psql -X -v ON_ERROR_STOP=1`을 사용한다.
- 실제 테이블 목록과 개수, FK, UNIQUE·CHECK, 인덱스를 승인 ERD 및 데이터 사전과 비교해 누락이나 불일치를 기록한다. 초안의 10개 테이블 수는 로컬 재현에만 사용한다.
- 유효한 입력 1건 이상과 FK 또는 CHECK 위반으로 거부되는 입력 1건 이상을 검증한다.
- 구현 PR에 테스트한 커밋 SHA, 재현 명령, 결과, 영향 범위, 미해결 항목을 남긴다. 리뷰와 CI를 확인하고 CI가 범위를 모두 검증하지 못하면 `PARTIAL`로 기록한다.

## 확인이 필요한 항목

- T05 승인 ERD와 데이터 사전의 기준 커밋
- T08 마이그레이션 번호, 적용 순서, 기존 초안과의 적용 관계
