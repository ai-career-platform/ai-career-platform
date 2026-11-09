# T43 진행 기록

## T43 범위 내 코드 통일

- GapSkill/GapJobRole 중복 정의를 제거하고 catalog의 Skill/JobRoleRef 재사용.
- CurrentUserDep를 라우터 인자로 직접 받고, 서비스 의존성 이름은 ServiceDep로 통일.
- catalog의 job_roles/skills/job_role_skills와 my_skills의 user_skills 선언 재사용.
  T43에서 필요한 나머지 테이블 선언은 모듈 수준으로 이동.
- T33 방식의 _run으로 SQLAlchemy 오류를 rollback 후 공통 503 AppError로 변환.
  로그에는 오류 클래스명만 기록. 서비스의 commit/rollback 책임은 유지.
- 기존 ListCursor와 공통 derive_key를 재사용. T43 용도 키파생 함수 제공.
  사용자/직무 조건·시각 검증·정규 인코딩 검증은 T43에서 유지.
- cursor 형식이 기존 T43 초안과 달라져 이전 초안 cursor는 INVALID_CURSOR가 된다.
  현재 미등록 Draft이므로 운영 배포된 cursor 마이그레이션은 아님.
- T43 테스트 전체 **111 PASS**, DB17개 포함. 오류 변환5개/서명 시각 검증3개 추가.
- 기존 경고1개. 공통 코드·다른 담당 파일 변경 없음. 미커밋·미푸시.
- 운영 provider는 여전히 미연결(503). 승인 모델/stale 정책/공통 등록은 임의 변경하지 않음.

## 추가 HTTP 검증 (main e1e8591)

- 최신 공통 CSRF 보호에 맞춰 T43 인증 TestClient에 X-CSRF-TOKEN:1 적용.
- 실제 T26+PostgreSQL을 HTTP 생성/Location 상세/직무 필터 이력/빈 cursor 거부로 검증.
- 타인 결과404 및 빈 이력을 확인. 사용자 신원과 stale 판정만 명시적 테스트 대역.
- 같은 시각의 UTC/DB 세션 timezone 응답은 aware DTO로 비교한다.
- T43 전체 **103 PASS**, 실제 PostgreSQL **17개** 포함. 운영 인증 DB 통합은 미완료.
- 미커밋·미푸시이며 다른 담당자 코드/공통 등록 파일은 수정하지 않음.

## 최신 추가 작업 (main d0d18e1)

- T26 실제 계산 함수가 main에 병합됨. from_t26()로 기존 어댑터에 직접 연결.
- 실제 계산의 경계·NULL·미등록·결정성 검증 6개 추가.
- 실제 계산→PostgreSQL 저장→상세/이력 조회 및 NULL 원본 보존 검증 2개 추가.
- **T43 102 PASS**, 실제 PostgreSQL16개 포함. 저장용 모델 행과 stale 판정은 테스트 대역.
- 전체 backend 결과는 **422 PASS / 125 SKIP / 1 FAIL / 19 ERROR**.
  새 T49 문서 저장 테스트에서 Windows의 0700 권한 검사 오류가 발생함.
  해당 담당 코드나 보안 검사는 수정하지 않음. 전체 PASS를 주장하지 않음.
- 실제 운영 승인 버전 선택·stale 정책·공통 라우터 등록·HTTP 통합 검증은 남음.
- 공유 DB/DDL/Seed·다른 담당 코드 변경 없음. 검증 후 임시 DB 종료, 테스트 잔여0건.
- 이번 수정은 미커밋·미푸시. 아래는 이전 시점의 기록.

담당 임서현 · 기준 main `8fb7c3b` · 상태 PARTIAL

- Pydantic DTO, 생성·상세·이력 라우터, T15 인증 연결 구현.
- SQLAlchemy 입력 조회·승인 rule 모델 확인·수치 snapshot 저장·소유자 조회 구현.
- 서명 cursor, 시각/UUID keyset 페이징, 저장 실패 rollback 검증.
- 실제 T26은 복제하지 않고 어댑터로 주입. stale 판정기도 필수 주입.
- 최신 main에서 삭제한 인증 provider 대신 공통 테스트 helper 재사용.
- 최신 실행: backend 전체 **369 PASS / 112 SKIP / 기존 경고 1개**.
- T43 서비스/DTO/어댑터/실제 JWT 로직 검증 **80 PASS**.
- T43 PostgreSQL 테스트 14개는 이번 실행 환경 미설정으로 skip.
- 이전 main `254d342`에서는 격리 PostgreSQL 18.4에 정식 T09/T10을 적용해
  DB 테스트 **14 PASS**, Seed 33개 검산 통과 및 테스트 잔여 데이터 0건 확인.
  이후 추가된 migration 0002까지 검증한 결과로 취급하지 않는다.

실제 T26 계산·승인 버전 연결, 입력 변경/삭제 stale 정책, provider·공통 라우터
등록, 실제 인증/계산/DB 통합 검증, CI·리뷰·완료 승인이 남았다.
T33 및 목표 직무 API는 main에 추가됐으나 실제 수정→재분석 통합은 미검증이다.
공통 코드·DDL·Seed·공유 서비스는 변경하지 않았다. T17 로컬 문서도 보존했다.

```powershell
cd C:\dev\ai-career-platform\backend
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

변경 파일은 미커밋 상태이므로 실행 SHA는 아직 없다. 위 SHA는 기준 main이다.
커밋 후 재검증해 PR에 실제 실행 SHA를 기입해야 한다.
PR 준비: [T43_PR_DRAFT.md](T43_PR_DRAFT.md).
