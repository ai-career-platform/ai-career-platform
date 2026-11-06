# AI Career Platform — 테스트 자동화·증빙 운영 가이드

> 대상: Windows 11 개발자 / GitHub PR 리뷰어 / PM. 기준: 2026-11-06 `main`에서 확인된 실행 도구. 이 문서는 운영 절차이며 테스트 PASS를 주장하지 않습니다.

## 1. 도구별 적용 현황

| 영역 | 도구 | 실제 설치·코드 | 기본 실행 |
|---|---|---|---|
| 정식 Backend | pytest + httpx | `backend/requirements-dev.txt`, `backend/tests/` 존재 | `python -m pytest -q` |
| Staging PoC Backend | pytest + httpx | `poc/staging/tests/` 존재. PoC requirements에는 pytest 없음 | 별도 개발환경에 설치 후 실행 |
| Frontend | Vitest + Testing Library | `frontend/package.json`, `frontend/src/*.test.*` 존재 | `npm test` |
| DB | Bash/psql + 격리 PostgreSQL | `database/tests/`와 개별 워크플로 존재 | 해당 테스트의 README/가드에 따름 |
| Browser E2E | Playwright | **미설치/미구현**. `playwright.config.*` 및 E2E 시나리오 없음 | 구현 PR 승인 전 실행 불가 |
| CI | GitHub Actions | 기본 CI smoke, DB 개별 작업 존재 | PR Checks 확인 |

**주의:** CI Smoke PASS는 Backend pytest/Frontend Vitest/E2E 전체 PASS를 뜻하지 않습니다. 작업별로 실제 실행한 명령과 증빙을 구분합니다.

## 2. 기능 단위 표준 프로세스

1. Redmine Issue와 테스트 범위(정상, 오류, 경계, 권한)를 정의합니다.
2. 로컬 격리 환경에서 자동화 테스트를 작성하고 실행합니다. 공유 Staging에서 DML·DDL·Seed·파괴적인 테스트 금지.
3. `PASS/FAIL/SKIP` 수, 테스트 명령, 환경, Git SHA, 테스트 로그/리포트를 기록합니다.
4. 실패를 수정하고 같은 명령으로 재실행합니다. 미실행은 PASS가 아닌 NOT_RUN/HOLD.
5. 개인 브랜치 PR에 코드 변경, 테스트 요약, 증빙 파일 또는 GitHub Actions Artifact URL을 첨부합니다.
6. CI 및 리뷰 완료 뒤 Squash Merge. Merge SHA와 승인 범위에 한해 Staging 읽기 전용/비파괴 검증 후 Redmine 종료합니다.

## 3. 실행 가이드

- [PYTEST_GUIDE.md](PYTEST_GUIDE.md): 정식 Backend와 PoC의 Python 환경 분리, pytest/JUnit XML.
- [VITEST_GUIDE.md](VITEST_GUIDE.md): React UI 단위 테스트/커버리지에 관한 현재 범위.
- [PLAYWRIGHT_GUIDE.md](PLAYWRIGHT_GUIDE.md): 브라우저 E2E 도입 절차 및 향후 명령 예시(아직 미설치).
- [TEST_EVIDENCE_GUIDE.md](TEST_EVIDENCE_GUIDE.md): 필수 증빙, 경로, 보안, PR/Redmine 보고.
- [TEST_REPORT_TEMPLATE.md](TEST_REPORT_TEMPLATE.md): 테스트 결과 보고 복사 양식.
- [기여·PR 정책](../CONTRIBUTING.md) / [Backend 설정](../development/BACKEND_DEVELOPMENT_SETUP.md) / [Frontend 설정](../development/FRONTEND_DEVELOPMENT_SETUP.md).

## 4. 판정 규칙

- **PASS**: 지정 범위의 테스트를 실제 실행했고 전부 성공, 증빙 확보.
- **FAIL**: 하나 이상 실패 또는 테스트 실행 자체가 오류.
- **HOLD**: 환경·승인·선행 기능 미준비로 검증 불가능. 원인/담당/후속작업 지정.
- **NOT_RUN**: 아직 실행하지 않음(예정/기대 결과를 PASS로 기재 금지).
- **SKIP**: 명시적으로 제외된 테스트. 개수와 제외 근거를 기록하며 임의로 PASS에 합산하지 않음.

권한/데이터 변경 테스트는 반드시 별도 로컬·격리 DB에서 진행합니다. Staging은 명시적 승인 없이 조회·헬스체크로 제한합니다.
