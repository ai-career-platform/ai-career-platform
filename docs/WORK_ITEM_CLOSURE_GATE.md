# 개발 일감 공통 종료 게이트 — Auto-CD → Staging QA → Redmine CLOSED

> **적용:** AI Career Platform 전체 개발 일감 T01~T150 및 향후 신규 일감. 기존 개별 지시서의 DoD와 함께 **의무 적용**하며, 충돌 시 이 문서의 종료 게이트를 우선 적용합니다.  
> **성격:** 작업 수행·완료 판정 규칙. 이 문서를 병합하는 행위 자체가 스테이징 배포/검증 성공이나 Redmine 일감 종료를 의미하지 않습니다.

## 기본 원칙

**`PR MERGED ≠ AUTO-DEPLOY SUCCEEDED ≠ STAGING QA PASS ≠ REDMINE CLOSED`.**

- 코드 변경은 PR 리뷰·필수 CI 통과 후 `main`에 Squash Merge한다.
- **배포 대상에 포함되는 변경**은 `main` 병합을 트리거로 하는 **기존 자동 배포** 결과를 확인한다. 수동 재배포를 기본 업무 단계로 추가하지 않는다.
- 자동 배포는 `main` 커밋·CI 확인 → GitHub Actions `staging-publish.yml`의 검증된 이미지/배포 신호 게시 → Ubuntu `ai-career-staging-deploy.timer`의 1분 주기 Poll/Compose 반영으로 구성된다. **타이머가 동작한다는 사실만으로 배포 성공을 추정하지 않는다.**
- 중요한 범위 제한: 게시 워크플로가 만드는 이미지는 **`poc/staging/backend` 및 `poc/staging/frontend`**를 빌드한다. 따라서 `main`에 병합된 다른 디렉터리의 코드(예: `crawler/`, `backend/training_jobs_api.py`)가 스테이징에서 실제 실행된다고 자동 가정하지 않는다. 컨테이너 이미지의 포함 경로·서비스 실행 여부를 확인하여 미포함 기능은 `DEPLOY_SCOPE_GAP/HOLD`로 기록한다.
- Staging 기능 검증은 **실제 스테이징 URL/실행 환경**에서 수행한다. 로컬·Mock·CI 테스트를 Staging PASS로 대체하지 않는다.
- 서버에 접근할 수 없거나 자동 배포가 실패·지연·미대상인 경우 `NOT_VERIFIED/HOLD` 및 책임자·재검증 시점을 기록하고 Redmine 일감을 CLOSED로 변경하지 않는다.

## 기능 개발 일감의 필수 종료 흐름

| 단계 | 게이트 | 필요한 증빙 | 실패·미확인 시 |
|---|---|---|---|
| 1 | DEV 및 LOCAL_QA | 요구 범위, 테스트 명령/실행 결과, 로컬 SHA | 개발 진행/HOLD |
| 2 | PR_REVIEW/CI | PR URL, 승인 리뷰·필수 Checks, 보안·DB 변경 승인 | Review/HOLD |
| 3 | MAIN_MERGED | Squash Merge 커밋 SHA | Review 유지 |
| 4 | AUTO_DEPLOY | 배포 대상 포함 여부, publish run/배포 신호, Ubuntu timer/service 실행 결과, 실제 배포 SHA·이미지 Digest·시간 | `DEPLOY=HOLD` |
| 5 | STAGING_QA | 실제 스테이징 URL, `/api/version` 등의 실행 SHA/버전, 해당 기능 API/DB/화면(가능 범위), 정상·오류 사례, 결과 및 로그/화면 증빙 | `STAGING_QA=HOLD/FAIL` |
| 6 | EVIDENCE_REVIEW | PR/CI/배포/기능 테스트 증빙을 Redmine Issue에 연결, PM/JM 확인 | Review/HOLD |
| 7 | REDMINE_CLOSED | 담당 권한자가 진척률 100%, 상태 Closed, 종료일·근거 등록 | 미충족 시 미종료 |

**모든 해당 게이트가 증빙으로 PASS여야 100%/CLOSED.** CI 성공과 Health Check만으로 기능 테스트까지 성공했다고 쓰지 않는다.

## Staging 확인 체크리스트 (자동 배포 후)

1. GitHub `main` 병합 SHA와 **배포 신호/Manifest의 source SHA** 및 실제 스테이징 `/api/version`/로그에 기록된 **실행 버전**을 대조한다. Squash Merge SHA 및 코드 SHA가 다를 수 있으므로 실제 게시 기준 SHA와 대상 서비스의 코드/이미지 포함 관계를 명시한다.
2. GitHub `staging-publish.yml`의 작업 결과와 배포 신호(없음/실패 시 HOLD), Ubuntu `ai-career-staging-deploy.service`/timer 실행 로그의 성공·실패 기록을 확인한다. CI와 게시가 성공하더라도 서버 Pull/배포 완료를 보증하지 않는다.
3. 해당 기능이 **스테이징 서비스 이미지/라우팅에 포함되었는지** 확인한다. 일반 Health API만 있는 PoC에 실제 크롤러 기능이 자동 배포됐다고 기록하지 않는다.
4. 기본 비파괴 확인: Frontend `/`, API `/api/health`, `/api/version`, `/api/health/db`와 해당 일감의 실제 화면·API 시나리오. HTTP 200만으로 데이터·기능 품질 PASS 선언 금지.
5. DB 쓰기·실제 수집·스케줄 활성화·Migration·Seed·부하 테스트가 필요한 경우에는 **스테이징 영향범위와 승인**을 사전 확인하고 격리 테스트/읽기 전용 증빙을 우선 사용한다. 승인 없는 공용 DB DDL/DML, 기존 볼륨 초기화, 다른 서비스 변경은 금지.
6. 장애 시 관련 서비스만 조사하고 배포 SHA, 실패 원인, 복구/후속 이슈를 기록. 다른 Docker 프로젝트/볼륨/포트/Secrets 보호.

## 예외: 문서·설계·조사 등 비배포 일감

- 실행/배포 대상이 **본질적으로 없는 일감**은 PM/JM이 Redmine에 `DEPLOY_APPLICABILITY=N/A`와 사유, 대체 검증(문서 리뷰·링크·승인·정합성 검사) 및 승인자를 **사전 또는 종료 전 명시**한 경우에만 자동 배포/실기능 QA 대신 해당 증빙으로 종료할 수 있다.
- 코드 변경을 수반하지만 현재 Auto-CD 이미지에 포함되지 않는 작업은 **N/A가 아니라 `DEPLOY_SCOPE_GAP/HOLD`**다. 별도 스테이징 연동 작업/검증 일감을 연결하고 PM/JM이 범위 분할·종료 기준을 승인하기 전 임의 종료하지 않는다.
- Staging 접근 불가·환경 미준비·자동 배포 실패는 N/A가 아니다.

## Redmine 완료 댓글 필수 양식

```text
[개발 일감 종료 게이트]
Issue / Owner:
PR URL / 승인자 / CI Run URL:
Main Merge SHA:
Staging 배포 대상 포함: YES / NO / N/A (근거):
Auto-CD Publish Run URL / 결과:
Ubuntu Pull 배포 실행 증빙 / 시각(KST):
배포 Manifest SHA / 이미지 Digest:
Staging 실제 실행 SHA / Version:
Staging URL / 실제 검증 시나리오:
Staging API / Frontend / DB: PASS / FAIL / NOT_VERIFIED / N/A (증빙 URL):
기존 데이터·서비스 영향 및 복구 여부:
DEPLOY: PASS / HOLD / N/A
STAGING_QA: PASS / HOLD / N/A
EVIDENCE: PASS / HOLD
PM/JM 확인자 / 확인일:
REDMINE: CLOSED / REVIEW / BLOCKED
잔여 Blocker / 후속 Issue:
```

**판정:** `DEPLOY=PASS`는 **해당 기능이 포함된 대상 이미지의 서버 배포 성공**을 뜻한다. `STAGING_QA=PASS`는 **실제 그 기능을 스테이징에서 검증**한 경우에만 사용한다. 별도 학습용 로컬 서버 결과를 스테이징 결과로 기록하지 않는다.

## 관련 문서

- [GitHub 협업 및 리뷰](CONTRIBUTING.md)
- [CI/CD 게시·자동 Pull](CI_CD.md)
- [Ubuntu Staging 운영](STAGING.md)
- [Redmine 규정](REDMINE.md)
- [QA 증빙 표준](testing/TEST_EVIDENCE_GUIDE.md)
