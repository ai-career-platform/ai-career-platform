# 테스트·증빙·완료 기준

## 코드 PR
- 기능 테스트: 정상 / 오류 / 경계 / 미존재 / 권한 없음.
- API: Request/Response 계약 및 Swagger 재현 결과.
- DB: 트랜잭션, Unique/FK 제약, 쿼리, 연결 실패 시 예외 처리.
- Frontend: Preview/화면 캡처, 로딩·빈 결과·오류 상태.
- AI: 점수 의미(예: 매칭 점수는 채용 성공 확률이 아님), 모델 버전·평가 기준·실패 시 대체.
- 보안: Secrets 스캔, 인증/인가, 입력/출력 검증.
- 재실행 가능한 명령과 사용 환경을 기록하고 Mock PASS와 실환경 PASS를 분리.

## 공통 증빙 단계
| 단계 | 최소 증빙 |
|---|---|
| 개발 시작 | Redmine 10%, 브랜치, 작업 범위 |
| PR 리뷰 요청 | Redmine 90%, PR URL, 테스트 결과, CI URL |
| 리뷰/승인 | GitHub 리뷰 댓글, 해결된 대화, CI 결과 |
| Merge | Squash Merge SHA |
| 완료 | Staging 확인 결과, Redmine 100% Closed |

## 현재 CI 주의
PR #1 CI는 단순 Smoke 테스트이므로, PASS만으로 Python/Frontend/DB/AI 기능이 검증된 것은 아닙니다. CI 강화 전에는 필요한 로컬 테스트 증빙을 추가합니다.

## T28 경량 Frontend CI (학습용 프로젝트)
- `.github/workflows/frontend-ci.yml`은 `frontend/**`, 해당 workflow, 또는 이 문서를 변경한 PR에서 `npm ci` → `npm run lint` → `npm test` → `npm run build`를 실행합니다. `build`에 TypeScript 타입 검사가 포함됩니다.
- 실행 환경은 GitHub Actions Ubuntu + Node.js 24이며, Frontend CI는 **실제 Backend/DB/브라우저·Staging 통합 검증의 대체가 아닙니다.**
- PR의 **Checks → Frontend CI**에서 실행 SHA·PASS/FAIL을 확인합니다. 로컬 재현은 `cd frontend; npm ci; npm run lint; npm test; npm run build`입니다.
- 실패 탐지는 개인 작업 브랜치에서 일부러 문법 오류를 넣어 해당 CI가 FAIL인지 확인한 뒤, 오류를 복구한 최종 커밋에서 PASS인지 재검증합니다. **고의 오류를 main에 병합하지 않습니다.**
- 기존 Smoke/Backend/PostgreSQL CI와 Auto-CD는 그대로 유지합니다. 경로 필터가 걸린 이 workflow를 모든 PR에서 반드시 성공해야 하는 필수 체크로 지정하면 스킵된 PR이 대기할 수 있으므로 브랜치 보호 규칙에서 주의합니다.

## 배포 게이트
- SHA·이미지 Digest·CI 성공·승인 상태 확인.
- 배포 전 디스크·RAM 및 기존 18개 운영 컨테이너 상태 점검.
- 배포 후 Frontend/API/DB HTTP 200 및 오류 로그 확인.
- 확인하지 못한 항목은 PASS가 아니라 `NOT_VERIFIED` 또는 `HOLD`.

## 테스트 데이터
Staging 공통 Seed/샘플 데이터는 유지하되 CI 자동화 테스트는 분리된 DB 또는 트랜잭션으로 격리합니다. 배포 시 DB 초기화 금지.

## 배포 후 기능별 필수 QA 및 종료 게이트

[공통 종료 게이트](WORK_ITEM_CLOSURE_GATE.md)를 모든 개발 작업 DoD에 추가 적용합니다. **`LOCAL QA PASS`와 `CI SUCCESS`, `main MERGED`는 `STAGING QA PASS`의 대체 근거가 아닙니다.** 기존 자동 Publish 및 Ubuntu Pull/Compose 적용을 확인한 뒤 Manifest·실제 실행 SHA·이미지 Digest를 대조하고, 실제 스테이징에서 변경 API/Frontend/DB의 정상·실패·빈 결과 등을 범위에 맞게 확인하세요. 현재 PoC 컨테이너에 포함되지 않은 모듈은 `DEPLOY_SCOPE_GAP/HOLD`입니다. 민감정보를 제거한 Evidence를 Redmine에 등록하고 PM/JM 확인 후에만 100%/Closed. 비배포 작업은 승인된 N/A 대체 기준을 따릅니다.
