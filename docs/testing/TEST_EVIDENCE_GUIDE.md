# 테스트 실행 증빙·결과 보고 표준

> 목적: 개발자·리뷰어가 **어떤 코드에 대해 어떤 테스트를 실제로 실행했는지** 재현 가능하게 남깁니다.

## 1. PR 제출 시 필수 기록

| 구분 | 필수 내용 |
|---|---|
| 식별 | Redmine Issue URL, PR URL, 담당자, 브랜치/HEAD SHA |
| 범위 | 변경 파일·기능, 테스트 종류(pytest/Vitest/Playwright/DB/manual) |
| 재현 | OS/Python·Node/Postgres 버전, 실제 실행 명령·작업 디렉터리 |
| 결과 | 총 테스트, PASS, FAIL, SKIP, NOT_RUN/HOLD 및 이유, 프로세스 종료 코드 |
| 증빙 | 콘솔 로그, JUnit XML/HTML Report/스크린샷 중 해당 산출물의 정확한 파일명·URL |
| 영향 | Staging 변경 여부, DB DDL/DML/Seed 여부, 비밀값 포함 여부(반드시 NO) |
| 검토 | GitHub Actions Run URL, 리뷰 요청, 남은 위험·후속 Issue |

테스트를 실행하지 않았거나 리포트가 생성되지 않으면 `NOT_RUN`/ `HOLD`로 기록합니다. 로컬 테스트 PASS와 GitHub Actions PASS를 분리합니다.

## 2. 증빙 저장 권장 구조

```text
test-results/                           # 각 개발자 로컬 생성물: 기본적으로 Git에 커밋하지 않음
├── pytest-junit.xml
├── pytest-console.log
├── vitest-console.log
└── playwright/                        # 도입 후에만 생성
    ├── playwright-report/
    └── trace-and-screenshots/
```

**권장:** 일회성 결과 파일은 GitHub Actions Artifact 또는 Redmine 비공개 첨부로 공유합니다. PR 본문에는 *민감정보를 제거한* 요약과 정확한 URL을 적습니다. PR에 대용량/개인정보가 포함된 HTML·trace를 직접 커밋하지 마세요. 가이드·샘플 마크다운은 `docs/testing/`에 버전 관리합니다.

## 3. 첨부 절차

1. 기능 브랜치 HEAD SHA 기록: `git rev-parse HEAD`.
2. 각 테스트 실행. 터미널 종료 코드와 테스트 개수 기록.
3. 파일 생성 확인: `Test-Path .\test-results\pytest-junit.xml` 등.
4. 로그·스크린샷·trace에서 비밀번호, API 키, Bearer 토큰, 쿠키, 실제 이름·이메일, DB 접속 문자열, 내부 민감 요청/응답 제거.
5. PR에 테스트 요약과 GitHub Actions URL을 붙임. 로그/리포트는 승인된 비공개 채널로 첨부.
6. CI 실패 또는 불일치 발견 시 수정 PR 업데이트 후 재실행. 과거 PASS 로그를 새 SHA의 증빙으로 재사용하지 않음.
7. Merge SHA, 승인 범위의 Staging 확인 내용, 잔여 HOLD를 Redmine에 반영.

## 4. 판정 및 마감

- `PASS`: 증빙이 있는 해당 테스트 범위 한정 통과.
- `FAIL`: 실패/에러가 있음. 즉시 원인과 재현 방법 기술.
- `HOLD`: 기능·계정·승인·환경 등 외부 선행조건 미충족.
- `SKIP`: 제외 테스트 수와 이유 기록.
- `SECURITY=FAIL`: 토큰/비밀번호/개인정보가 리포트나 PR에 포함됨 → 공유 중단 및 보안 조치.

**Staging에는 읽기 전용/비파괴 검증만 허용**하며 DB migration/seed, 쓰기, 권한 변경, 운영 부하 테스트는 별도 승인 절차를 따릅니다.

## 5. 리뷰 요청 예시

```text
[PR 테스트·Merge 검토 요청]
Redmine: #....
PR: https://github.com/ai-career-platform/ai-career-platform/pull/...
HEAD SHA: ...
검증 환경: Windows 11 / Python 3.12 / Node LTS / 로컬 격리 DB
Backend: pytest ... PASS x / FAIL 0 / SKIP y (실행 명령 ...)
Frontend: Vitest ... 또는 NOT_RUN(사유)
Browser E2E: Playwright NOT_INSTALLED 또는 PASS ... (도입 후)
CI: Actions URL / PASS 또는 HOLD
증빙: JUnit XML/스크린샷/HTML report 위치 ...
Staging DB 변경: NO
Secret/PII 첨부: NO
잔여 리스크/HOLD: ...
```

[보고 양식](TEST_REPORT_TEMPLATE.md)에서 복사하여 사용합니다.

## 6. main 병합 이후: 필수 Auto-CD / Staging QA / Redmine 증빙

모든 개발 작업은 **[종료 게이트](../WORK_ITEM_CLOSURE_GATE.md)**를 따라야 합니다. 다음 기록이 없으면 **완료/100%/Closed 선언 금지**입니다.

- Squash Merge SHA 및 실제 자동 Publish 워크플로 URL·결과, 배포 Manifest의 SHA/Digest.
- Ubuntu timer/service에서 실제 Pull/배포 성공한 시간과 실행 SHA·버전 (`/api/version` 등).
- 해당 기능이 빌드 이미지/스테이징 서비스 **실제로 포함되는지** 확인 결과. PoC 기본 Health PASS만으로 Crawler 등 독립 모듈 배포 성공 처리 금지.
- 변경 기능에 대응하는 Staging URL, API/Frontend/DB 검증 시나리오, 기대/실제 결과, 비밀값 제거한 로그/스크린샷.
- `DEPLOY` 및 `STAGING_QA`의 `PASS/FAIL/NOT_VERIFIED/HOLD/N/A`, 담당 검수자와 Redmine 변경 결과.
- 자동 배포 미반영·서버 접근 불가·이미지 범위 밖은 HOLD. 문서 등 배포 비대상은 PM/JM의 N/A 및 대체 검증 승인 근거가 있어야 합니다.
