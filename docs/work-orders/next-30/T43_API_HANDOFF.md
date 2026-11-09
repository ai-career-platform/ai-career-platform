# T43 연결 안내

코드 통일: Skill/JobRoleRef·테이블 선언·CurrentUserDep·ListCursor를 기존 코드에서
가져다 사용하며 공통 원본은 변경하지 않았다. ServiceDep로 서비스 의존성을 표기한다.
services.skill_gaps.derive_cursor_key(secret)는 공통 derive_key와 T43 용도 문자열을 사용한다.
운영 provider에 이 키를 공급하는 연결은 아직 하지 않았다. 커서 형식 변경으로
이전 T43 초안 cursor는 재사용할 수 없으며 첫 페이지부터 다시 조회해야 한다.

최신 main d0d18e1에는 T26이 병합됐다. T26SkillGapEvaluator.from_t26(model_version)으로
실제 calculate_skill_gap을 연결할 수 있으며 실제 계산+DB 검증까지 통과했다.
이 함수는 모델 승인을 만들어 주지 않는다. 저장소는 approved_at을 검사한다.
stale 정책과 운영 provider·라우터 등록은 여전히 남아 있다.

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
판정 함수는 사용자·평가 ID·평가 시각을 받지만 삭제까지 감지할 증빙 정책은 미확정이다.
T26 어댑터에는 실제 calculate 함수, Requirement 생성자, 기대 rule 버전과
승인된 모델 버전 DTO를 주입한다. 테스트의 고정 계산 결과는 실제 T26이 아니다.

provider는 현재 503을 반환하며 공통 앱에는 라우터를 등록하지 않았다.
공통 등록·설정 변경은 사용자 확인 후 진행한다.
실제 인증/결과 DB와 계산을 함께 쓰는 HTTP 통합 검증이 남아 있다.
검증 및 상태는 [T43_PROGRESS.md](T43_PROGRESS.md) 참조.
