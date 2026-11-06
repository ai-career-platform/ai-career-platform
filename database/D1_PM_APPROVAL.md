# D1 PM 승인 기록 — 2026-11-06

> 의사결정: **INITIAL_SCHEMA_APPROVED_FOR_CONTROLLED_D2_PREPARATION**  
> 승인 근거: PM이 이 대화에서 "설계 확인했고 승인 해도 문제 없을거 같은데 이어서 진행하면 될까요?"라고 의사표시한 후 계속 진행 요청.  
> 범위 제한: 초기 10개 테이블 설계 초안에 대한 진행 승인으로 해석. **PR Merge 승인이나 실제 Staging DB 변경 명령에 대한 포괄적 승인으로 확대하지 않음**.

## 승인 대상으로 간주하는 항목

- `database/README.md`에 정리된 사용자·프로필·기업·직무·기술·채용공고 중심 초기 10개 테이블.
- `database/migrations/DRAFT_0001_initial_schema.sql`의 PostgreSQL 18.1 독립 검증 PASS를 바탕으로 D2 구축 준비 진행.
- 기존 PostgreSQL 데이터 및 Named Volume 보존, Migration과 앱 자동배포 분리.
- Reader/App/Migrator/Admin 최소권한으로 설계.

## 유보 및 후속 검토

- 화면/API별 실제 수용기준, Redmine 원본 요구사항은 아직 미확인.
- 인증 및 개인정보·탈퇴/보존 정책, 채용공고 출처·이용권한은 미확정.
- `user_job_bookmarks`는 MVP 필수 기능으로 검증되지 않은 임시 테이블.
- Seed 정확한 건수와 데이터 분류는 별도 검증 필요.
- 기존 FastAPI 앱의 DB 접속 계정·연결 설정은 아직 검증되지 않음.
- PR #2의 운영 정책 문서가 main에 반영되지 않았고 일부 자동배포 현황이 오래됨.

## 독립 안전 검증 (완료)

- Staging 백업 아카이브 생성 및 `pg_restore --list` 검사 PASS.
- 독립 PostgreSQL 18.1 일회용 컨테이너 복원 PASS.
- 격리 SQL 테스트: [Actions 42149590877](https://github.com/ai-career-platform/ai-career-platform/actions/runs/42149590877) PASS.

## D2 착수 안전 원칙

1. 우선 권한 SQL 및 테스트를 GitHub 브랜치에 작성, 격리 DB에서 검증.
2. 실제 DB 변경은 명령·영향 범위를 출력해 **단계별 적용**하고, 변경 전 현재 컨테이너/볼륨 및 백업 증빙을 재확인.
3. Staging 계정 비밀번호/토큰은 GitHub 파일, PR, 채팅에 남기지 않음.
4. 변경 실패 시 Staging 데이터 자동 초기화, 무단 강제 롤백, `docker compose down -v` 금지.
5. 개발 서비스 연결 계정 교체는 기존 서비스 설정을 검토한 후 별도 승인·헬스검증.

**D1 설계 진행 승인:** YES(범위 제한).  
**D2 격리 테스트:** PROCEED.  
**D2 Staging 실제 배포:** 검증·적용 절차 완성 후 단계별 확인.
