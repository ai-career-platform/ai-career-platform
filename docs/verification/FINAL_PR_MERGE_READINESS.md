# 전체 기능 PR 병합 준비 상태 (2026-11-14 야간 기준)

GitHub 실제 조회(`gh pr view`, statusCheckRollup, reviews) 결과를 근거로 합니다. 이 문서는 조회 시점의 상태이므로, 병합 직전에 다시 조회해야 합니다.

- main: `1797f4c`
- 기준 검증: #360 `3e2565f`
  - CI 10/10 PASS
  - PostgreSQL 18.1
  - Migration 0001~0010 PASS
  - Backend 2147 passed / 0 failed / 82 skipped
  - Frontend·offline-tests PASS

## 1. 전체 PR 현황

**기능 PR**

| PR | 내용 | head → base | HEAD | Migration(diff) | CI | 리뷰 요청 | 승인 | Mergeable |
|---|---|---|---|---|---|---|---|---|
| #348 | 지원 이력(T101~T103) + 알림함(#350 포함) | feat/t101-job-applications-e2e → **main** | cf3a3b3 | 0004, 0005 | 9 pass | yg920 | 0 | MERGEABLE / BLOCKED(리뷰) |
| #351 | 개인정보 내려받기(T141~T143) | feat/t142-personal-data-export → feat/t97-notifications-inbox | 86ac09b | 0006 | 4 pass | yg920 | 0 | MERGEABLE / CLEAN |
| #352 | 공개 포트폴리오(T128~T130) | feat/t129-public-portfolio-sql → feat/t142-personal-data-export | 38859a2 | 0007 | 9 pass | yg920 | 0 | MERGEABLE / CLEAN |
| #354 | 알림 채널 분리·본인 변경 알림 없음 | fix/t96-channel-filter-and-events → feat/t129-public-portfolio-sql | f8e5ebd | 없음 | 1 pass | yg920 | 0 | MERGEABLE / CLEAN |
| #355 | 기업 조직(T122~T124) | feat/t122-organizations-sql → feat/t129-public-portfolio-sql | 125bd82 | 0008 | 9 pass | yg920 | 0 | MERGEABLE / CLEAN |
| #357 | 기업 공고(T125~T127) | feat/t125-company-postings-sql → feat/t122-organizations-sql | d2ef21f | 0009 | 9 pass | yg920 | 0 | MERGEABLE / CLEAN |
| #359 | 관리자 검수(T80~T82) + PM 결정 | feat/t81-moderation-cases-sql → feat/t125-company-postings-sql | a93d8ae | 0010 | 5 pass | yg920 | 0 | MERGEABLE / CLEAN |
| #347 | 관리자 감사 화면 실제 API | feat/t85-admin-audit-real-api → **main** | e83a3fa | 없음 | 3 pass / **offline-tests fail** | yg920 | 0 | MERGEABLE / BLOCKED |
| #346 | 고급 공고 검색 실제 API | feat/t100-advanced-search-real-api → **main** | 1037c57 | 없음 | 3 pass / **offline-tests fail** | yg920 | 0 | MERGEABLE / BLOCKED |
| #349 | T125·T128 DDL 설계(제안) | docs/t125-t128-db-design → **main** | 2b97f55 | 없음(proposed) | 8 pass | yg920 | 0 | MERGEABLE / BLOCKED(리뷰) |

참고:
- #350은 이미 #348 브랜치에 squash 병합됐습니다(`cf3a3b3`, 계정 GilbertMoon, 이 세션의 명령 아님). 다시 병합하지 않습니다.
- 쌓인 PR(stacked PR)은 base가 보호 규칙 없는 기능 브랜치라서 `CLEAN`으로 표시됩니다. 그래도 **독립 리뷰 없이 병합하지 않습니다.**
- 쌓인 PR의 CI 수가 적은 이유: backend·frontend workflow는 main 대상 PR에서만 실행됩니다. 같은 커밋을 검증 PR(#353·#356·#358·#360)로 실행한 결과가 9~10 pass로 함께 집계됩니다.

**검증 전용 PR (병합 금지, 모두 Draft·제목에 "ci-only … DO NOT MERGE")**

| PR | 검증 범위 | HEAD | CI |
|---|---|---|---|
| #353 | 0004~0007 스택 | 38859a2 | 9 pass |
| #356 | ~0008 | 125bd82 | 9 pass |
| #358 | ~0009 | d2ef21f | 9 pass(frontend 1회 flaky 후 재실행 PASS) |
| #360 | 0001~0010 + #354 (`verify/full-stack-0010`) | 3e2565f | 10 pass |

## 2. 실제 의존성 그래프

```
main ─┬─ #348 (0004, 0005 ← #350 포함)
      │    └─ #351 (0006)  [base: feat/t97-notifications-inbox = #350 head]
      │         └─ #352 (0007)
      │              ├─ #354 (migration 없음)
      │              └─ #355 (0008)
      │                   └─ #357 (0009)
      │                        └─ #359 (0010)
      ├─ #347 (독립, #348의 Dockerfile 고정 커밋 필요)
      ├─ #346 (독립, 같은 이유)
      └─ #349 (설계, 0007·0009와 내용 중복)
```

- #354는 #352 위의 **형제 브랜치**라 #355~#359에는 들어 있지 않습니다.
- #360 검증 브랜치에서는 merge로 함께 검증했습니다(충돌 없음).

## 3. 권장 병합 순서

1. **#348** → main (0004·0005, #350 포함)
2. **#351**: base를 main으로 변경한 뒤 diff가 #351 변경(28 files, 0006)만인지 확인 → 병합
3. **#352**: base main, 0007만 → 병합
4. **#354**: base main, 알림 수정만 → 병합(#355보다 먼저 또는 뒤, 코드 충돌 없음)
5. **#355**: base main, 0008 → 병합
6. **#357**: base main, 0009 → 병합
7. **#359**: base main, 0010 → 병합
8. **#347**, **#346**
   - #348 병합 뒤 각 브랜치에 main을 **merge**(rebase·force push 금지)해서 공통 Dockerfile 고정을 받습니다.
   - offline-tests PASS를 확인한 다음 병합합니다.
   - `frontend/src/api/index.ts`, `env.ts`, `AppLayout.tsx`, 스테이징 가드에서 충돌이 예상되며, 양쪽 항목을 모두 남기는 방식으로 해결합니다.
9. **#349**
   - DDL이 이미 0007·0009로 구현됐습니다.
     - T128 제안 DDL은 0007에 모두 포함됩니다.
     - T125 제안 DDL과 0009의 차이는 `DROP TRIGGER IF EXISTS`, `CREATE OR REPLACE FUNCTION`뿐입니다.
   - 그대로 병합하면 같은 스키마의 출처가 둘이 됩니다. PM이 둘 중 하나를 정해야 합니다.
     - (a) 설계 문서만 남기고 `database/proposed/T125*·T128*`와 해당 테스트를 지움
     - (b) 대체됨(superseded)으로 닫음

각 단계마다 확인할 것:
- 리뷰 승인
- 필수 CI(`CI Smoke Test`) 포함 전체 체크
- Migration 번호 연속성: T115 gate가 main 대비 빈 번호를 거부합니다.
- 병합 후 다음 PR의 base 변경과 CI 재실행

## 4. 리뷰 현황

- 기능 PR 10건 모두 yg920에게 리뷰를 요청했습니다(중복 요청은 하지 않음).
- **승인 0건.**
- main 보호 규칙:
  - 승인 1명, push하면 이전 승인 해제, 리뷰 스레드 해결 필수
  - squash만 허용, 필수 체크 `CI Smoke Test`
- 리뷰어가 볼 내용은 각 PR 본문에 있습니다(목적, 범위, 선행 PR, 테스트, Migration, 위험).
- 가장 먼저 리뷰할 것은 **#348**입니다(스택 전체의 시작점).

## 5. CI 현황

- 실패: #346·#347의 `offline-tests`
  - 원인: 스테이징 이미지에 `VITE_JOB_SEARCH_ADVANCED_UI`·`VITE_ADMIN_AUDIT_UI`를 `=false`로 고정하는 변경이 #348(`f709934`)에만 있습니다.
  - #348 병합 뒤 main을 merge하면 해결될 것으로 예상합니다. **아직 확인하지 않았습니다.**
- 나머지 기능 PR: 실패 체크 없음
- 알려진 flaky
  - `frontend/src/pages/MyData.test.tsx` "re-auth older than 10 minutes asks again before downloading"(포커스 타이밍)
  - #358에서 1회 실패 후 재실행 PASS
  - #351 영역. 스택 병합 뒤 후속 수정 대상입니다.

## 6. Merge Conflict

- 조회 시점에 모든 PR이 `MERGEABLE`입니다.
- 예상 충돌(병합 순서상): #346·#347과 스택 사이의 `frontend/src/api/index.ts`, `frontend/src/config/env.ts`, `frontend/src/layouts/AppLayout.tsx`, `poc/staging/frontend/Dockerfile.integrated`, `poc/staging/tests/test_frontend_react_image.py`
- 해결 원칙: 플래그는 하나만 추가하고 모두 `=false`로 고정합니다.

## 7. Migration 의존성

| 번호 | PR | 의존 |
|---|---|---|
| 0004 job_applications | #348 | 0001 |
| 0005 notifications | #348(#350) | 0001 |
| 0006 personal_data_requests | #351 | 0001 |
| 0007 public_portfolio | #352 | 0001(`user_experiences`·`user_projects`에 UNIQUE 추가) |
| 0008 organizations | #355 | 0001 |
| 0009 company_postings | #357 | 0008 |
| 0010 moderation_cases | #359 | 0009(`company_posting` 대상) |

- 반드시 이 순서대로 병합해야 합니다. 번호가 비거나 순서가 바뀌면 T115 gate가 실패합니다.
- **GCP Cloud SQL에는 0002~0010 모두 미적용입니다**(#344 절차와 별도 승인 필요).

## 8. 정책·운영 차단 항목 (승인 전 BLOCKED)

- `company_direct`의 실제 `license_ref`(약관 버전)
  - 지금은 테스트 Fixture 값 `TEST-FIXTURE-NOT-A-TERMS-VERSION`뿐입니다.
  - 운영에서는 source 행이 없어 승인 시 503이 나고, 아무것도 공개되지 않습니다.
- 운영 Seed: `admin.content.review` 권한, `public_profile` 동의 정책, `company_direct` source
- 신규 기능 플래그 운영 활성화(서버 9개 이상 + VITE UI 플래그)
- GCP 운영 Migration, Cloud SQL 변경, 운영 배포
- 실제 이메일 발송
  - 메일 공급자 미정이라 기업 초대 생성·재발송은 503입니다.
- 기타 정책 질문
  - 게시된 기업 공고의 takedown을 검수 경로로 보낼지
  - 개인정보 Export를 DB에 보관하는 것과 백업 보존
  - Export worker 스케줄
  - Google 전용 계정 재인증
  - 조직 정보 수정 액션(T121에 없음)

## 9. 야간 E2E 상태

- Workstream: `wt-e2e` / `test/full-system-e2e`(기준 85ab49d)
- **IN_PROGRESS**: 로컬 커밋은 있으나 원격 push·PR은 아직 없습니다.
- #359 최종본(a93d8ae)을 merge해서 검수 시나리오 9건을 실행하도록 지시했습니다.
- Browser E2E 결과: **NOT_RUN**(조회 시점)

## 10. 내일 실행 절차

1. yg920 리뷰 확인: `gh pr view 348 --json reviewDecision,reviews`
2. #348 승인 시:
   - `gh pr merge 348 --squash`(보호 규칙 충족 시에만)
   - main 최신 SHA 기록
3. #351 base 변경: `gh pr edit 351 --base main`
   - `gh pr view 351 --json files`로 0006과 #351 파일만인지 확인
   - CI 전체(backend PG18 포함) 실행·확인 → 리뷰 승인 → squash
4. #352 → #354 → #355 → #357 → #359 순서로 3과 같이 진행합니다.
   - 각 병합 뒤 `python -B database/migrate.py lint`, `database/gate/t115_migration_gate.py pr --base-ref origin/main`
5. #347·#346: main을 merge → offline-tests 확인 → 리뷰 → squash
6. #349: PM 결정(a/b)에 따라 정리
7. 검증 PR #353·#356·#358·#360: 스택 병합이 끝나면 닫습니다.
8. 후속
   - MyData flaky 테스트 수정
   - 야간 E2E PR 리뷰와 결함 처리
   - #344 GCP Migration 0002~0010 적용 승인 절차
