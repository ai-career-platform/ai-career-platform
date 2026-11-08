# Redmine 세부일감·진척률 운영

| 시점 | 진척률 | 상태 예시 | 담당 |
|---|---:|---|---|
| 세부일감 등록 | 0% | New | 개발자 |
| 실제 작업 착수 | 10% | In Progress | 개발자 |
| 개발·자체 테스트 완료 + PR 생성 + Slack Merge 요청 | 90% | Review | 개발자 |
| 승인·Squash Merge + 필요한 Staging 확인 완료 | 100% | Closed | PM/JM |

## 운영 세칙
- 상위 일감은 Epic/기능 단위, 세부일감은 단일 검증 가능한 결과 단위로 작성합니다.
- 모든 PR 본문에 Redmine Issue 링크 또는 번호를 남깁니다.
- 90%는 **리뷰 대기**이지 개발 완성/배포 성공과 동일하지 않습니다.
- 리뷰 수정 요청, CI 실패, 충돌 발생 시 90% 유지하며 원인·대응 기록.
- Merge 후 Staging 검증 실패 시 90% 유지하고 장애/수정 이슈를 연결합니다.
- 작업 중단은 진척률을 임의로 100%로 올리지 말고 Hold/Blocked 상태와 사유 기록.
- 상위 일감 진척률은 하위 세부일감 기준으로 집계하는 것을 권장하되 실제 Redmine 설정과 일치하는지 관리자 확인 필요.

## 세부일감 기본 양식
```text
제목:
목표 및 사용자 시나리오:
범위/비범위:
담당자:
선행조건:
관련 화면/API/DB:
완료조건(테스트·증빙 포함):
예상 일정:
브랜치 / PR / Merge SHA:
Staging 검증 결과:
```

## 종료 증빙
GitHub PR URL, CI 실행 URL, 테스트 결과, 필요 시 Swagger/Preview 화면, Merge SHA, Staging 확인 기록을 연결합니다.

## 종료 조건 — 전체 개발 일감 강제 적용

**[공통 종료 게이트](WORK_ITEM_CLOSURE_GATE.md)**를 T01~T150 및 신규 작업지시서에 적용합니다. 90% Review 단계와 100% Closed 사이에 다음이 **모두 증빙으로 완료**되어야 합니다.

1. PR 승인/CI PASS 및 `main` Squash Merge SHA 확인.
2. 기존 **자동 배포**의 게시 성공·Ubuntu Pull/적용 성공 및 변경 기능이 실제 배포 이미지에 포함됐는지 확인.
3. Staging의 **실행 SHA·버전/이미지 Digest**와 배포 Manifest 대조.
4. 해당 변경 기능의 실제 Staging API·DB·Frontend 정상/오류 테스트 및 비파괴 Evidence 확보.
5. Redmine 댓글에 PR/CI/배포/테스트 URL, 결과, 보류 사유, PM/JM 검수 기록.
6. 조건 모두 PASS이면 권한 있는 담당자가 **진척률 100% 및 Closed** 처리.

`MERGED ≠ DEPLOYED ≠ STAGING_QA_PASS ≠ CLOSED`. 자동 배포가 실패했거나 실행 기능이 이미지에 포함되지 않았다면 `HOLD/BLOCKED` 유지. **문서/설계만 있는 비배포 일감**에 한해 PM/JM 승인과 구체적 N/A 근거·대체 검증을 등록하면 종료할 수 있습니다. 코드가 배포 이미지에 없다는 사실 자체는 N/A가 아닙니다.
