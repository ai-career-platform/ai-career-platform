# T150 — 기업·학습 확장 릴리스 최종 Gate·인수 (Go/No-Go)

> **판정: NO_GO** (2026-11-11, 기준 main `822fa16660afdaa5ad099f059b244216332becf1`)
> - 이 문서는 **배포 지시가 아닙니다.** 사실과 근거, GO 조건만 기록합니다. Staging·운영·DB는 변경하지 않았고, 이번 판정을 위해 Staging에 접속하지 않았습니다.
> - **PM의 명시적 승인 없이 GO를 선언하지 않습니다.** 증빙이 부족한 항목은 PASS로 올리지 않습니다.
> - T120(확장 1차, NO_GO)의 P0 문제(E5 Migration, E6 취약점)가 **해결되지 않았으므로** 그대로 이어서 기록합니다.
> - 이번 T138~T156 실행에서 열린 PR은 **미병합**입니다. 그래서 릴리스 범위가 아니라 증빙(PR)으로만 표시합니다.

## 1. 증빙 구분

| 표기 | 뜻 |
|---|---|
| MAIN | main 병합 + main CI 통과 |
| PR | 열린 PR의 CI·로컬 결과(미병합 → 릴리스 범위 아님) |
| ISOLATED | 일회용 DB·로컬 서버 등 격리 환경 |
| NOT_VERIFIED / NOT_RUN | 확인 못 함 |

## 2. 릴리스 추적 체인

| 단계 | 값 | 출처 | 구분 |
|---|---|---|---|
| main HEAD | `822fa16660afdaa5ad099f059b244216332becf1` (T120 #227 병합) | `git rev-parse origin/main` | MAIN |
| main CI | CI 42973091668 · Backend tests 42973091658 · T49 upload E2E 42973091579 · Crawler MVP 42973091627 모두 success. Frontend CI 는 직전 커밋 843cac9(42973054445) success(822fa16 은 문서 변경만) | `gh run list --branch main` | MAIN |
| 이미지 게시 | "Publish verified Staging release" run **42973326842** success, run_number 191 | GitHub Actions | MAIN |
| 배포 manifest | `release.json`: sha = `822fa166…`, ci_run_id = 42973091668 | 산출물 `verified-staging-release` | MAIN |
| Backend 이미지 | `ghcr.io/ai-career-platform/ai-career-platform-backend@sha256:33874911d4119b9b465cce87be6dc6ec43f51a6470dcb0cdb8d2eb99959ab831` | manifest | MAIN |
| Frontend 이미지 | `ghcr.io/ai-career-platform/ai-career-platform-frontend@sha256:8297a34023dd1da9be13e8c568811394f37e044f8335309eedac58d50fa82c0a` | manifest | MAIN |
| Staging 실행 중 digest | **NOT_VERIFIED** (호스트 `docker inspect`·`.deploy-state` 확인 필요, 접근 없음) | — | NOT_VERIFIED |

## 3. 선행 일감 현황 (T120, T127, T130, T136, T143, T144, T148, T149)

| 선행 | 상태 | 릴리스 반영 |
|---|---|---|
| T120 확장 Gate | 병합(#227), **NO_GO** (재평가: E5·E6 FAIL/P0) | 판정 근거 |
| T127 기업 공고 콘솔 UI | 병합(#224), **Mock 전용 플래그** | 운영 기능 아님 |
| T130 공개 포트폴리오 UI | 병합(#222), **Mock 전용 플래그** | 운영 기능 아님 |
| **T136 학습 진도 대시보드** | **NOT_STARTED**(PR 없음) | 없음 |
| T143 내 데이터 UI | **PR #237 OPEN**(Mock 전용) | 없음 |
| T144 문서 저장소 보안 | **PR #232 OPEN** — 평문 저장 F-1(High) 기록 | 없음 |
| T148 다중 역할 E2E | **PR #241 OPEN** | 없음 |
| T149 비용·용량 | **PR #236 OPEN** | 없음 |

## 4. Gate 항목

| # | Gate | 결과 | 근거 | 구분 |
|---|---|---|---|---|
| F1 | 최종 main SHA·CI | **PASS** | §2. main 의 모든 워크플로 success | MAIN |
| F2 | 실행 이미지 digest | **PARTIAL** | manifest digest 확인. Staging 실행 중 digest NOT_VERIFIED | MAIN / NOT_VERIFIED |
| F3 | Staging 배포 상태 | **NOT_VERIFIED** | 접속하지 않음. T90 G8(Staging Frontend 가 React 앱이 아님) 이후 재확인 증빙 없음 | NOT_VERIFIED |
| F4 | Database Migration | **FAIL (P0)** | T120 E5 그대로. Staging 0002·0003 미적용·원장 없음(#178 OPEN). 확장 기능 새 표(T96·T99·T101·T122·T125·T128·T139·T142·T145)는 전부 제안 DDL. T155 #233 의 크롤러 0011 은 PR 상태 | MAIN / PR |
| F5 | 개인정보 접근·삭제 | **FAIL (P0)** | T141 정책 PROPOSED(#230). T142 API 는 플래그 꺼짐·저장소 없음(#235). T143 Mock 전용(#237). T90 G3(탈퇴 후 물리 삭제·보존 기간) 미해결 | MAIN / PR |
| F6 | 암호화·키 관리 | **FAIL (P0)** | T144(#232): **문서가 디스크에 평문 저장**(F-1, High). 봉투 암호화 계약·키 회전은 시뮬레이션만, 라우터 미연결. AES-GCM 의존성 미승인. 호스트 볼륨 암호화·TLS NOT_VERIFIED | PR |
| F7 | 기업·개인·관리자 권한 E2E | **PARTIAL (P0)** | T148(#241): 필수 10개 시나리오 PASS(실제 라우터 + 메모리 저장소, 관리자·IDOR 는 실제 PostgreSQL). 기업·포트폴리오 DB 저장소가 없어 실제 DB 경계는 HOLD. F-2 수정 포함 | PR / ISOLATED |
| F8 | 브라우저 E2E | **PARTIAL** | T117(병합): Mock 30 · 로컬 실제 API 34 PASS. 이번 실행: T140·T143·T146·T156 헤드리스 Chrome(로컬). **Staging E2E NOT_RUN** | MAIN / PR / ISOLATED |
| F9 | 백업·복원 | **PARTIAL (P0)** | T114(병합) 격리 복원 훈련. T149(#236) 182 MiB 합성 DB 복원 3회(4.8~6.1초, 로컬). **Staging 실제 백업 NOT_VERIFIED**, 스케줄·암호화 미적용 | MAIN / PR / ISOLATED |
| F10 | 운영 비용·용량 | **PARTIAL** | T149(#236): 로컬 실측(시드 11.2 MiB, 5천 사용자 182 MiB) + 12개월 추정. AI 비용은 추정(T110 미착수). RTO/RPO PROPOSED | PR |
| F11 | 미해결 Critical/High | **FAIL (P0)** | starlette HIGH 3건(예외 `approved_by` 비어 있음 → 무효), 컨테이너 이미지 스캔 NOT_RUN, T144 F-1(High, 평문 저장). CRITICAL 은 T118 병합으로 0건 | MAIN / PR |
| F12 | 담당자 인수인계 | **PARTIAL** | Runbook 은 있음(§7). 담당자 지정 없음. T138(김예주 #154)·T140(조영우) 담당 작업 대기 | MAIN / PR |
| F13 | 선행 일감 완료 | **FAIL** | §3: T136 NOT_STARTED, T143·T144·T148·T149 미병합, T127·T130 Mock 전용 | MAIN / PR |

## 5. 판정

**NO_GO.**

해결되지 않은 P0 가 있습니다.
- **F4**: Migration. T120 E5 가 그대로 남아 있습니다.
- **F5**: 개인정보 반출·삭제가 실제로 동작하지 않습니다.
- **F6**: 문서가 평문으로 저장됩니다.
- **F11**: HIGH 취약점이 남아 있고 예외는 승인되지 않았습니다.

F2·F7·F9 도 P0 인데 PARTIAL 입니다. 선행 일감 T136 은 시작도 하지 않았습니다. Staging 은 T90/T120 판정 그대로 **PoC 운영 상태**를 유지합니다. 기업·포트폴리오·개인정보 요청 기능은 모두 **기본 꺼짐**입니다.

## 6. GO 조건 (모두 충족 + PM 명시 승인)

1. **F4**
   - #178 기준선 승인 → Staging migration 원장 정리
   - 켤 기능의 정식 migration 승인·적용(T115 게이트: 백업 → 검증 → 사전 점검 → 수동 적용)
2. **F5**
   - T141 정책 승인(§9 6개 결정)
   - T142 저장소·Worker(T145)·암호화 저장소(T144) 연결 후 실제 DB 시험
   - T90 G3 물리 삭제 작업 구현·승인
3. **F6**
   - 문서 저장 암호화 적용(AES-256-GCM 의존성·키 보관 위치 승인)
   - 기존 평문 문서 이행
   - 호스트 볼륨 암호화·TLS 확인
4. **F11**
   - starlette 해결: FastAPI 업그레이드 또는 만료일 있는 예외에 승인자 기입
   - 컨테이너 이미지 스캔 PASS
5. **F7**: 기업·포트폴리오 DB 저장소 승인 후 T148 시나리오를 PostgreSQL 층으로 PASS
6. **F9**: Staging 실제 백업 → 격리 복원 훈련, 스케줄 등록(승인)
7. **F2·F3**: 호스트 운영자가 실행 중 digest = manifest digest 임을 확인하고, React 앱 Staging 배포 후 Staging E2E PASS
8. **F13**: T136 착수·완료, T143·T144·T148·T149 병합

## 7. 인수인계 (역할 — 담당자 지정 필요)

| 영역 | 문서 | 담당 역할 |
|---|---|---|
| 개인정보 요청 | `docs/privacy/T141_DATA_SUBJECT_REQUEST_POLICY.md`(#230), `docs/privacy/T142_PERSONAL_DATA_EXPORT_API.md`(#235) | 개인정보 보호 담당 |
| 문서 저장소 보안 | `docs/security/DOCUMENT_STORAGE_SECURITY_RUNBOOK.md`(#232) | 보안 담당 |
| 백그라운드 작업 | `docs/architecture/BACKGROUND_JOB_CONTRACT.md`(#234) | Backend |
| i18n·접근성 | `docs/frontend/I18N_A11Y_STANDARD.md`(#231) | Frontend |
| 용량·비용·복구 | `docs/ops/CAPACITY_COST_PLAN.md`(#236) | DevOps |
| 권한 회귀 | `backend/tests/test_t148_multi_role_security.py`(#241) | QA·보안 |
| 기술 자동완성 | `docs/api/T139_SKILL_SUGGEST_API.md`(#238) | Backend(T140 담당: 조영우) |
| 크롤러 관리자 | T155(#233)·T156(#240)·T152 보완(#242) | 크롤러(문길래) |
| 기존 운영 문서 | `docs/release/EXPANSION_RELEASE_GATE.md`(T120) §8 | 각 담당 |

## 8. 결정 기록

| 날짜 | main SHA | 판정 | 결정자 | 비고 |
|---|---|---|---|---|
| 2026-11-11 | `822fa16` | NO_GO | (PM 승인 대기) | 최초 판정(T150). P0: F4·F5·F6·F11 FAIL, F2·F7·F9 PARTIAL |
