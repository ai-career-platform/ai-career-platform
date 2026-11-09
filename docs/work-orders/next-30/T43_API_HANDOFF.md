# T43 연결 안내

최신 T06 계약 기준이며 원 지시서의 /analyze는 구 경로다.

| 경로 | 정상 응답 |
|---|---|
| POST /api/v1/skill-gaps | 201 SkillGap + Location |
| GET /api/v1/skill-gaps/{assessment_id} | 200 SkillGap |
| GET /api/v1/skill-gaps | 200 SkillGapSummaryPage |

사용자 ID는 T15 CurrentUserDep에서만 받는다. body는 job_role_id만 허용한다.
상세는 타인·없는 결과 모두 404. 목록은 본인+선택 직무 필터로 조회한다.
limit 기본20/최대100, cursor는 사용자·필터에 결합하며 최소32바이트 키가 필요하다.
시각/UUID 내림차순 정렬이며 전체 snapshot 격리는 보장하지 않는다.

SqlSkillGapRepository는 Session과 필수 stale_checker를 받는다.
저장된 요구/관측/gap 수치는 유지하지만 직무/기술 명칭은 현재 참조값이다.
판정 함수는 사용자·직무·평가 시각을 받지만 삭제까지 감지할 증빙 정책은 미확정이다.
T26 어댑터에는 실제 calculate 함수, Requirement 생성자, 기대 rule 버전과
승인된 모델 버전 DTO를 주입한다. 테스트의 고정 계산 결과는 실제 T26이 아니다.

provider는 현재 503을 반환하며 공통 앱에는 라우터를 등록하지 않았다.
공통 등록·설정 변경은 사용자 확인 후 진행한다.
실제 인증/결과 DB와 계산을 함께 쓰는 HTTP 통합 검증이 남아 있다.
검증 및 상태는 [T43_PROGRESS.md](T43_PROGRESS.md) 참조.
