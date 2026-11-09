# T151 STEP 03 — 격리 PostgreSQL 실 DB 검증 결과

> Feature: Redmine #1578 · Task: T151 · STEP: 03  
> 검사 기준 SHA: `9d8b359177d7a1d4b7762f2c462451eb4730f7c7`  
> 증빙 제공자: 로컬 Codex 실행 결과(사용자 보고), **GitHub에서 원본 로컬 로그는 직접 열람하지 못함**  
> 이 문서는 제공된 실행 결과를 추적 가능한 형태로 정리한 보고이며 재실행/재검증을 주장하지 않음.

## 1. 보고된 검증 결과

| 항목 | 결과 |
| --- | --- |
| 격리 DB 연결 | PASS |
| T151 Migration 적용 | PASS |
| 초기 검색어 Seed | 6/6 |
| 검색어 CRUD | PASS (soft-delete) |
| 작업 생성 멱등성 | PASS (동시 생성 포함) |
| 작업 상태 전이 | PASS |
| 검색어↔공고 발견 관계 | PASS |
| Migration 재실행 | PASS |
| rollback/복원 | PASS (트랜잭션 취소·백업 복원; 별도 down Migration 없음) |
| T64 회귀 테스트 | 15/15 PASS |
| 전체 보고된 검증 | 30/30 PASS |
| 스테이징 DB 변경 | NO |
| Live 수집 | HOLD |
| 테스트 DB | 검증 후 종료 |
| 사용자 보고 BLOCKERS | 없음 |

검증 구성: 실제 격리 DB 검사 9개, 기존 T151 계약 검사 6개, T64 회귀 15개.

## 2. 증빙 원본 위치 (로컬, GitHub에는 업로드하지 않음)

- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step03-evidence.json`
- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step03-real_pg.log`
- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step03-existing_and_t64.log`

주의: 경로는 사용자 제공값. 현재 GitHub에는 실행 로그 파일 본문이 없으므로 로그 해시 및 세부 검사별 출력은 별도 확인 대상.

## 3. GitHub 코드 재확인

현재 `crawler/storage/migrations/0003_keywords_jobs.sql`에는 세 테이블 및 초기 검색어 6개 Seed가 포함됨. `crawler/jobs/keyword_management.py`는 내부 메타데이터 관리 기능이며 외부 요청이나 실제 예약 Worker 구동을 호출하지 않음.

## 4. T151 완료 전 남은 확인 사항

1. **검색어 변경 감사 이력**: 현 코드의 `search_keywords.updated_at`은 마지막 변경 시각만 제공. 누가/언제/무엇을 변경했는지 기록하는 내역은 구현되지 않았으므로 T151 원래 DoD 대비 미완료. 관리자 API/RBAC(T155)에서 액터를 제공할 때 통합할지, T151에 별도 감사 기능을 추가할지 명시적으로 결정해야 함.
2. **실제 staging 적용과 Fixture 스모크 검증**: 이번 STEP03은 새 **격리 DB**만 검사함. staging 7개 기존 공고와 T64 실행 이력 보존을 실환경에서 검증하는 절차는 별도 단계로 수행.
3. **롤백 표현**: down Migration 스크립트는 없음. 검증 범위는 트랜잭션 취소 및 백업 복원으로 기술해야 정확함.
4. **실제 큐/Worker 연결**: 의도적으로 후속 T152~T154 범위. T151 단독 DoD에서 요구하지 않음.

## 5. 제안되는 후속 조치

- STEP04: 변경 이력 요구사항 최소 설계 및 코드 보완/테스트, GitHub CI 검증.
- STEP05: 기존 staging 시스템 snapshot 확인 후, **별도 명시적 승인된 수동 Migration**과 Fixture 테스트; Live/Timer는 비활성 유지.
- 실패 시 기존 데이터 백업으로 복원하며 기본 운영 서비스와 Auto-CD는 건드리지 않음.

## 6. 단계별 상태

```
FEATURE=1578
TASK=T151
STEP=03
MAIN_SHA=9d8b359177d7a1d4b7762f2c462451eb4730f7c7
ISOLATED_DB=PASS
TESTS=30/30_PASS_USER_REPORTED
STAGING_DB_CHANGED=NO
LIVE_COLLECTION=HOLD
T151_OVERALL=IN_PROGRESS
NEXT=STEP04_AUDIT_REQUIREMENT
```
