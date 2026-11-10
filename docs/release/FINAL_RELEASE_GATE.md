# T90 — 최종 릴리스 Gate (Go/No-Go)

> **판정: NO_GO** (2026-11-11, 기준 main `1f3cecd6bfb3883f978d20ee2f63dee3f9321e14`)
> 이 문서는 **운영 배포 지시가 아닙니다.** 판정 근거와 GO까지의 조건을 기록합니다. Staging·운영·DB는 변경하지 않았습니다.
> 함께 보는 문서: [RELEASE_TEST_MATRIX.md](RELEASE_TEST_MATRIX.md), [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md), [T30 증빙](../deployment/RELEASE_EVIDENCE.md)

## 1. 증빙 구분 규칙

| 표기 | 의미 |
|---|---|
| **MAIN** | main에 병합된 코드·시험, main CI로 확인 |
| **PR** | 미병합 PR 기준 — main 검증 결과가 아님 |
| **MOCK** | Mock·가짜 Adapter 검증 — 실제 연동 아님 |
| **ISOLATED** | 로컬 일회용 DB·서버 검증 |
| **STAGING-RO** | Staging 읽기 전용 확인(GET만) |
| **NOT_VERIFIED** | 확인하지 않음 / 할 수 없음 |

## 2. 배포 추적 체인 (main SHA → 이미지 → Staging)

| 단계 | 값 | 출처 | 구분 |
|---|---|---|---|
| main HEAD | `1f3cecd6bfb3883f978d20ee2f63dee3f9321e14` (T86 #188 병합) | `git rev-parse origin/main` | MAIN |
| main CI | CI·Backend tests·T49 E2E·Crawler MVP 모두 success (CI run 42839167343) | `gh run list --branch main` | MAIN |
| 이미지 게시 | "Publish verified Staging release" run **42839451480** success, run_number 153 | GitHub Actions | MAIN |
| 배포 manifest | `release.json`: sha = `1f3cecd…`, ci_run_id = 42839167343 | 게시 run artifact `verified-staging-release` | MAIN |
| Backend 이미지 | `ghcr.io/ai-career-platform/ai-career-platform-backend@sha256:c919cf22e75711de60c7ff6b9883d393fc320d819be0f7310b2a81212469d8b2` | manifest | MAIN |
| Frontend 이미지 | `ghcr.io/ai-career-platform/ai-career-platform-frontend@sha256:59c3a3407c4089cec90a7702a2a823933e705b7e2fc75434056963ea00d268e1` | manifest | MAIN |
| Staging 응답 버전 | `/api/version` → `{"environment":"staging-poc","version":"1f3cecd6bfb3883f978d20ee2f63dee3f9321e14"}` | GET 1회 (2026-11-10T15:23Z UTC) | STAGING-RO |
| Staging Health | `/` 200, `/api/health` 200, `/api/health/db` 200 | GET 각 1회 | STAGING-RO |
| Staging 실행 중 이미지 digest | **NOT_VERIFIED** — 호스트의 `docker inspect`·`.deploy-state/success.json` 확인 필요(서버 접근 없음) | — | NOT_VERIFIED |

Staging이 응답하는 SHA는 main HEAD와 같습니다. 다만 Staging Frontend는 **PoC 정적 상태 페이지**이고, React 앱(`frontend/`)이 아닙니다(T30 문서).

## 3. Gate 항목

| # | Gate | 결과 | 근거 | 구분 |
|---|---|---|---|---|
| G1 | 치명·고위험 보안 취약점 0 | **PASS** (Critical 0 / High 0) | T86 #188 병합, 보안 회귀 424건 CI PASS | MAIN |
| G2 | 중위험 보안 Finding 처리 계획 | **OPEN** | F-1 접근 로그의 `actor_user_id`(Medium, 배포 설정 PR 필요), F87-1 탈퇴·철회 감사 미기록(Medium, T83 승인 대기) | MAIN / PR |
| G3 | 개인정보 삭제·보존 | **FAIL (P0)** | 탈퇴 **접수만** 구현, 물리 삭제 작업 미구현·보존 기간 미승인. 철회·접수 전파는 E2E PASS | PR #189 (ISOLATED) |
| G4 | 필수 E2E | **PARTIAL** | Backend E2E·보안·개인정보 PASS. **React 앱 Staging 미배포**로 사용자 화면 E2E는 Staging에서 NOT_VERIFIED | MAIN / ISOLATED |
| G5 | 필수 CI | **PASS** (main) | main HEAD 모든 workflow success. T87·T88 PR CI PASS, T89 PR CI는 PR 기준 | MAIN / PR |
| G6 | 복원 절차 검증 | **PASS (격리)** | PostgreSQL 18.6 일회용 클러스터: pg_dump(-Fc) → pg_restore, 표 51개 내용 md5·객체 수 일치, 복원본에 앱 연결 200 | ISOLATED |
| G6b | Staging 실제 백업·복원 | **NOT_VERIFIED** | Staging DB 백업 접근 없음(이전 지시에서 HOLD) | NOT_VERIFIED |
| G7 | 승인되지 않은 DB Migration 없음 | **FAIL (P0)** | Staging DB에 Migration 기록 원장 없음, **0002·0003 미적용**(기준선 PR #178 OPEN). main 코드의 탈퇴 접수는 `scheduled_purge_at=NULL`로 저장하는데, 0001은 이 컬럼이 NOT NULL이고 0002가 제약을 풂 → **0002가 없는 Staging에서는 탈퇴 접수가 실패(503)할 것으로 예상**(코드·DDL 대조, Staging에서 실행하지는 않음) | MAIN / STAGING-RO 근거 문서 |
| G8 | 운영 계약 일치 | **FAIL** | (a) Staging Frontend가 React 앱이 아님, (b) G7 스키마 불일치, (c) T84 계약 차이 2건(400 BadCursor, 비용 헤더) T06 미반영 | MAIN |
| G9 | 성능 기준 | **N/A (기준 미승인)** | 기준선만 측정(T88 #190): 동시성 4~8에서 포화, 오류 0 | PR (ISOLATED) |
| G10 | 접근성 | **PASS (자동·Chrome·Edge)**, 스크린리더 NOT_RUN | T89 #191 | PR |
| G11 | Rollback 절차 | **문서화 / 미훈련** | CD는 이전 SHA로의 역방향 배포를 막음 → 되돌림 커밋으로 앞으로 배포가 기본. 수동 digest 고정은 승인 필요. DB는 forward-only라 백업 복원만 가능 | MAIN |

## 4. 판정

**NO_GO.** 해결되지 않은 P0 Gate가 있습니다.

- **G3**: 개인정보 물리 삭제 작업이 없습니다. 탈퇴 접수 후 데이터가 남는 기간이 정해지지 않았습니다.
- **G7·G8**: Staging DB 스키마가 main 코드와 어긋납니다(0002·0003 미적용, 원장 없음). 사용자 화면(React)도 배포되지 않았습니다.

P0이 남아 있으므로 GO를 선언하지 않습니다. 현재 Staging은 **PoC 운영 상태**로 유지합니다(T30 범위 PASS).

## 5. GO 조건 (모두 충족 + PM 승인)

1. PR #178(Migration 기준선) 승인·적용 → Staging 0002·0003 적용과 원장 기록(백업 후, 별도 승인)
2. 보존 기간 결정(T05/T83) → purge 작업 구현 → T87 시험 5(사전 검증)를 실제 작업으로 PASS
3. React 앱 Staging 배포(T19/T29 후속) → 사용자 여정 E2E(T92) Staging PASS
4. F-1 접근 로그 설정 PR, T83 감사 기록 결정
5. T87·T88·T89 PR 병합 후 main CI PASS
6. Staging 실제 백업 → 격리 복원 훈련(G6b), 실행 중 이미지 digest 확인(호스트 운영자)
7. 성능 합격 기준 승인(T88 제안 참고)

## 6. 판정 이력

| 날짜 | main SHA | 판정 | 비고 |
|---|---|---|---|
| 2026-11-11 | `1f3cecd` | NO_GO | 최초 판정 (T90) |
