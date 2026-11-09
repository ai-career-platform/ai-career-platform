# T43 진행 기록

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
