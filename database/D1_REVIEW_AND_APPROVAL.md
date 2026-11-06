# D1-10 — 초기 DB 설계 검토·승인 패키지

> 기준일: 2026-11-06 · `REVIEW_READY=YES` · `SCHEMA_APPROVED=NO` · `STAGING_APPLIED=NO`

## 1. 리뷰 범위와 변경 이력

- [DB 논리/물리 설계](README.md): 핵심 10개 테이블 후보, 컬럼 자료형 및 PK/FK/UNIQUE/CHECK/인덱스 설계.
- [기능↔테이블 추적표](REQUIREMENTS_MATRIX.md): 제품 구상과 도메인 테이블 연결, 확정 요구사항 부족 표시.
- [원본 조사 및 승인 질문](REQUIREMENTS_APPROVAL_CHECKLIST.md): MVP 기능/사용자 역할/인증/출처·보존 등 결정 대기 사항.
- [Migration 초안](migrations/DRAFT_0001_initial_schema.sql): PostgreSQL 18.1 대상 **비멱등 단발성 DDL 후보**. `career` 스키마·역할 생성이나 Seed·스키마 버전 관리는 포함하지 않음.
- [격리 DB 테스트](tests/test_initial_migration.sh): 환경변수 `D1_TEST_ONLY=YES`를 요구하고 일회용 `postgres:18.1` 컨테이너에서만 실행하는 검증.
- [GitHub Actions](../.github/workflows/d1-postgres-sql-test.yml): PR에서 테스트를 수행하며 Ubuntu Staging 호스트/비밀번호를 사용하지 않음.

## 2. 검증 증거

- 현재 PR 헤드: `7413b65470739953452e94ae690a3c0ca10d8c7a`.
- 일반 CI: [42149590886](https://github.com/ai-career-platform/ai-career-platform/actions/runs/42149590886) **SUCCESS**.
- 독립 PostgreSQL 통합 테스트: [42149590877](https://github.com/ai-career-platform/ai-career-platform/actions/runs/42149590877) **SUCCESS**.
- 해당 실행 로그 기준: 테이블 10개, 사용자 정의 인덱스 6개, FK 11개 생성 PASS. 정상 INSERT/FK, 중복 UNIQUE, 잘못된 CHECK, 없는 FK 거부, 중복 Migration 거부 및 트랜잭션 무결성 PASS.
- 최초 SQL 테스트 실행 [42149556505](https://github.com/ai-career-platform/ai-career-platform/actions/runs/42149556505)은 테스트 스크립트의 UUID 반환 문자열 처리 오류로 FAILED. 스크립트 수정 후 최신 SHA에서 PASS.
- **주의:** 이 검증은 문법·기본 DDL/제약조건 작동의 증거일 뿐 요구사항 완전성, DB 보안/계정, 대규모 성능, 복구 성공, 실제 Staging 적용 성공을 입증하지 않음.

## 3. 설계 승인 판단

| 심사 대상 | 상태 | 사유 |
|---|---|---|
| DDL 생성·기본 FK/제약조건 | **PASS** | 독립 PostgreSQL 18.1 실행 증빙 |
| D1 핵심 도메인 일관성 | **DRAFT** | 제품 상위 구상에 맞춰 제안, 실제 사용자 스토리 미반영 |
| MVP 기능/화면/API 범위 | **HOLD** | 확정 근거 문서·Redmine 원본 미확인 |
| 사용자·로그인·서비스 권한 모델 | **HOLD** | 인증/인가 방식과 사용자 종류 미결정 |
| 기업·공고 데이터 출처와 보존 | **HOLD** | 외부 데이터 사용권한/키/중복 규칙 미정 |
| 삭제·개인정보·Seed 정책 | **HOLD** | 삭제/보존과 공통 데이터 수용기준 미결정 |
| 실제 DB 소유권/권한 및 백업/복원 | **NOT VERIFIED** | 테이블/스키마/역할 목록만 읽기 전용 확인 |
| Staging Migration/Seed/Role 실제 적용 | **NOT STARTED** | 승인/백업/보안 게이트 미통과 |

**최종 결정: `D1_REVIEW_PACKAGE=READY`; `D1_SCHEMA_APPROVAL=HOLD`; `D2_EXECUTION=BLOCKED`.**

## 4. 리뷰 체크리스트 — PM/JM

- [ ] 서비스 MVP 요구사항 문서 또는 Redmine Epic·Story 링크 첨부.
- [ ] 실제 사용자 유형, 인증 방식, 역할/인가, 개인정보·탈퇴·보존 정책 합의.
- [ ] 초기 테이블 10개 각각의 API/화면 사용처를 연결하고 미사용/누락 테이블 판단.
- [ ] 북마크 `user_job_bookmarks`의 MVP 포함 여부 결정.
- [ ] 기업/공고 외부 데이터 출처·이용권한·중복 식별자 계약 승인.
- [ ] 직무/기술 분류체계와 Skill Gap 평가 척도 정의.
- [ ] PostgreSQL `career` 스키마 소유자, 최소권한 역할, 애플리케이션 접속 계정 전환 계획 승인.
- [ ] 백업 생성 및 격리 환경 복원 검증 계획 승인.
- [ ] Seed 합성 데이터 범위/버전 및 재실행 시 멱등성·보존 규칙 승인.
- [ ] 기존 PR #2 운영 문서의 오래된 자동 배포 현황을 최신 검증 결과로 수정.
- [ ] PM/JM 명시적 D1 승인(승인자·시점·관련 근거 기록).

## 5. D2 작업 분리 계획 — 아직 실행 금지

1. **D2-1 사전 점검:** 별도 호스트/DB 영향 조사, 디스크·백업·격리 복원 가능성 및 DB 소유권 확인.
2. **D2-2 권한 준비:** 최소권한 역할·스키마·객체 소유권·`search_path` 설계와 테스트. 기존 앱 런타임 연결 계정 변경은 별도 승인.
3. **D2-3 Migration:** **최종 승인 후** 단 한 번 실행되도록 Migration 버전 이력·사전/사후 검증을 구현. 파괴적 `DROP` 금지.
4. **D2-4 Seed:** 합성 데이터, 재실행 중복 방지, 출처/버전 기록.
5. **D2-5 통합 검증:** Reader 쓰기 거부, App DDL 거부, Migrator 권한 검증, Backend 연결/헬스, 기존 DB 컨테이너/볼륨 보존.
6. **D2-6 가이드:** DB 변경 요청/승인/실행/복구 Runbook 제공. 자동 앱 배포에 DB Migration 연결 금지.

**중요:** PR #5를 main에 Merge하면 기존 자동 앱 배포 파이프라인이 새 SHA를 인식할 수 있으므로, 문서/DDL 초안 PR이라도 승인 전 Merge하지 않는다. `main`에 반영되어도 Migration SQL이 자동으로 Staging DB에서 실행되어서는 안 된다.

## 6. PM 의사결정 기록 (작성 전)

```text
MVP 요구사항 URL / Redmine:
최초 구축에 반드시 필요한 기능:
초기 DB 테이블 확정:
미포함/후속 기능:
사용자 역할·인증:
개인정보·데이터 출처 정책:
스키마/백업/권한 승인:
PM/JM 리뷰어 및 승인 날짜:
승인 상태: HOLD
```
