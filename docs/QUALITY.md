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

## 배포 게이트
- SHA·이미지 Digest·CI 성공·승인 상태 확인.
- 배포 전 디스크·RAM 및 기존 18개 운영 컨테이너 상태 점검.
- 배포 후 Frontend/API/DB HTTP 200 및 오류 로그 확인.
- 확인하지 못한 항목은 PASS가 아니라 `NOT_VERIFIED` 또는 `HOLD`.

## 테스트 데이터
Staging 공통 Seed/샘플 데이터는 유지하되 CI 자동화 테스트는 분리된 DB 또는 트랜잭션으로 격리합니다. 배포 시 DB 초기화 금지.
