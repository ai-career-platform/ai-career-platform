# T120 — 확장 릴리스 Gate (Go/No-Go)

> **판정: NO_GO** (2026-11-11, 기준 main `ab567656eabb06d86e4cf9966c3bdfd042da8318`)
> - 이 문서는 **배포 지시가 아닙니다.** 사실과 근거, GO 조건만 기록합니다.
> - Staging·운영·DB는 변경하지 않았고, 이번 판정을 위해 Staging에 접속하지 않았습니다.
> - **PM의 명시적 승인 없이 GO를 선언하지 않습니다.**
> - T90(1차 릴리스, NO_GO)과 별개인 확장 단계 판정입니다. 대상은 T91~T119이고, **미병합·미구현 기능은 완료로 치지 않습니다.**

## 1. 증빙 구분

| 표기 | 뜻 |
|---|---|
| MAIN | main에 병합되어 main CI가 통과한 것 |
| PR | 열린 PR의 CI·로컬 결과. **병합되지 않았으므로 릴리스 범위가 아님** |
| ISOLATED | 일회용 DB·로컬 서버 등 격리 환경 결과 |
| NOT_VERIFIED / NOT_RUN | 확인하지 못함 |

## 2. 릴리스 추적 체인 (main SHA → 이미지)

| 단계 | 값 | 출처 | 구분 |
|---|---|---|---|
| main HEAD | `ab567656eabb06d86e4cf9966c3bdfd042da8318` (T103 #206 병합) | `git rev-parse origin/main` | MAIN |
| main CI | CI · Frontend CI · Crawler MVP success (CI run 42952038401) | `gh run list --branch main` | MAIN |
| 이미지 게시 | "Publish verified Staging release" run **42952231324** success, run_number 171 | GitHub Actions | MAIN |
| 배포 manifest | `release.json`: sha = `ab567656…`, ci_run_id = 42952038401 | 게시 run 산출물 `verified-staging-release` | MAIN |
| Backend 이미지 | `ghcr.io/ai-career-platform/ai-career-platform-backend@sha256:608f36334a2b02dd559c017f0ece93a1347f476024016b7b16f70f5be53fcd12` | manifest | MAIN |
| Frontend 이미지 | `ghcr.io/ai-career-platform/ai-career-platform-frontend@sha256:72721b53abae199641846eefc0840298152e1999f56f4a2e06fe0aee6f18e654` | manifest | MAIN |
| Staging 실행 중 digest | **NOT_VERIFIED**(호스트 `docker inspect`·`.deploy-state` 확인 필요, 접근 없음) | — | NOT_VERIFIED |

## 3. 확장 범위 (T91~T119) 현황

| 묶음 | 상태 | 릴리스 반영 |
|---|---|---|
| T91 MVP 범위 기준선 | 병합 | 기준 문서 |
| T92~T95(여정·검색·계정 복구 등) | 병합 | 일부 기능 플래그·Mock |
| T96~T103(알림·고급 검색·지원 기록) | 병합 | **서버 기능은 플래그 기본 꺼짐, 화면은 Mock 전용 플래그.** 제안 DDL만 있고 정식 migration 없음 → 운영 기능 아님 |
| **T104~T110** | **PR 없음(미착수)** | 없음 |
| T111~T119(운영 기반) | **PR 열림**(#207~#209, #211~#212, #216~#217, #225~#226) | **없음(미병합)** |

## 4. Gate 항목

| # | Gate | 결과 | 근거 | 구분 |
|---|---|---|---|---|
| E1 | 승인된 요구사항 범위 | **PARTIAL** | T91 기준선은 있음. T96~T103은 계약 PROPOSED·플래그 꺼짐. T104~T110 미착수 | MAIN |
| E2 | 테스트·CI | **PASS(main)** | main HEAD workflow 모두 success. T111~T119 PR CI는 각 PR 기준(§6 통합 보고서) | MAIN / PR |
| E3 | 실제 브라우저 E2E | **PARTIAL** | T117(#225): Mock 30 PASS, **로컬 실제 API 34 PASS**. **Staging E2E NOT_RUN**. Staging Frontend가 React 앱이 아님(T90 G8) | PR / ISOLATED |
| E4 | DB 백업·복원 | **PARTIAL** | 격리 복원 PASS(T90, T114 #211: 손상·잘린 덤프 FAIL 검출, 읽기 전용 백업 역할). **Staging 실제 백업 NOT_VERIFIED**, 스케줄·암호화 미적용 | ISOLATED |
| E5 | Migration 안전성 | **FAIL (P0)** | Staging에 0002·0003 미적용·원장 없음(T90 G7, 기준선 PR #178 OPEN). T115 게이트(#217)는 미병합. 확장 기능의 새 표(T96·T99·T101·T122·T125·T128)는 모두 제안 DDL | MAIN / PR |
| E6 | 취약점·Secret | **FAIL (P0)** | T118(#212) pip-audit: **main의 의존성에 30건**(PyJWT CRITICAL 1·HIGH 5, python-multipart HIGH 2, starlette HIGH 3 등). 수정 PR 미병합이며, 수정 후에도 starlette HIGH 3건이 남고 예외는 승인 대기. 컨테이너 스캔 NOT_RUN. Secret 위생 시험(T111 #207)은 미병합 | PR |
| E7 | 로그·지표·경보 | **FAIL** | T112(#208)·T113(#216) 미병합·미적용. 재설정 토큰이 Proxy 접근 로그에 남는 문제(T112 F-1, Medium) 미해결. 운영 경보 채널 없음 | PR |
| E8 | 롤백 계획 | **PARTIAL** | 문서화(T90 G11), 훈련 안 함. 기능은 플래그 끄기로 되돌릴 수 있음 | MAIN |
| E9 | 릴리스 SHA·digest | **PARTIAL** | main SHA와 이미지 digest는 manifest로 확인. Staging 실행 중 digest NOT_VERIFIED | MAIN / NOT_VERIFIED |
| E10 | 개인정보 | **OPEN** | T90 G3(탈퇴 물리 삭제·보존 기간) 미해결 상태를 다시 확인하지 않았음. 새 개인정보 표(T101 지원 기록 등)는 제안 단계 | MAIN |
| E11 | 운영 품질 점검 | **NOT_MEASURED** | T119(#226): 실측 기준선 없음(합성만), AI 품질 측정 없음(T105 미착수) | PR |
| E12 | 인수인계 | **PARTIAL** | 운영 Runbook 초안(T111·T113·T114·T115)은 PR에 있음. 담당자 지정 없음 | PR |

## 5. 판정

**NO_GO.**

해결되지 않은 P0가 있습니다.
- **E5**: Staging migration 불일치, 새 표 migration 없음
- **E6**: main 의존성의 CRITICAL·HIGH 취약점

릴리스 대상 운영 기반(T111~T119)도 하나도 병합되지 않았습니다. 그래서 확장 릴리스를 승인할 근거가 없습니다. 현재 Staging은 T90 판정 그대로 **PoC 운영 상태**를 유지합니다.

## 6. GO 조건 (모두 충족 + PM 명시 승인)

1. **E6**: T118 수정 PR 병합(PyJWT·python-multipart)과 starlette 해결. FastAPI 업그레이드 또는 승인된 예외(만료일 있음) 중 하나가 필요하고, 컨테이너 이미지 스캔도 해야 합니다.
2. **E5**:
   - #178 기준선 승인 → Staging migration 원장 정리
   - T115 게이트 병합
   - 확장 기능을 켤 경우 해당 새 표의 정식 migration을 승인·적용(백업 → 검증 → 사전점검 → 수동 적용)
3. **E7**: T112 병합과 Nginx 로그 형식·`X-Request-ID` 적용(승인), T113 경보 채널 지정
4. **E4**: Staging 실제 백업 → 격리 복원 훈련, 스케줄 등록(승인)
5. **E3**: React 앱 Staging 배포 후 T117 시나리오를 Staging에서 PASS
6. **E9**: 호스트 운영자가 실행 중 digest = manifest digest임을 확인
7. **E1**: 켤 기능 목록(플래그)과 계약 승인(T98·T101 등) 확정

## 7. 결정 기록

| 날짜 | main SHA | 판정 | 결정자 | 비고 |
|---|---|---|---|---|
| 2026-11-11 | `ab56765` | NO_GO | (PM 승인 대기) | 최초 판정(T120). P0: E5·E6 |

## 8. 인수인계 (역할)

| 영역 | 문서 | 담당 역할(지정 필요) |
|---|---|---|
| 환경·Secret | `docs/ops/ENVIRONMENT_MATRIX.md`, `SECRET_ROTATION_RUNBOOK.md`(#207) | 보안 담당 |
| 관측·장애 | `docs/ops/OBSERVABILITY.md`(#208), `INCIDENT_RUNBOOK.md`(#216) | Backend·운영 |
| 백업·Migration | `docs/ops/BACKUP_RESTORE_RUNBOOK.md`(#211), `MIGRATION_SAFETY_GATE.md`(#217) | DBA |
| 공급망 | `docs/security/SUPPLY_CHAIN_POLICY.md`(#212) | 보안 담당 |
| 품질 점검 | `docs/ops/QUALITY_SCORECARD.md`(#226) | 데이터·AI 담당 |
| API 호환 | `docs/api/API_COMPATIBILITY_POLICY.md`(#209) | Backend |
