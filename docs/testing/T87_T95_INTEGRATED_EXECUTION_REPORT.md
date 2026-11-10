# T87~T95 통합 실행 보고서

> 실행 2026-11-11 · 담당 문길래 · 실행 Claude Code · main 시작/종료 `1f3cecd6bfb3883f978d20ee2f63dee3f9321e14` (실행 중 main 변경 없음)
> 일감마다 최신 main에서 별도 브랜치·PR을 만들었고, 서로의 미병합 코드에 의존하지 않습니다. **병합한 PR은 없습니다.** 모든 PR에 Crasnec 리뷰를 요청했습니다.

## 1. 결과 요약

| Task | Implementation | Tests (로컬) | CI | PR | Status | Blocker |
|---|---|---|---|---|---|---|
| T87 | 동의 철회·탈퇴 전파 E2E, 사용자 FK 25개 삭제/보존 분류 게이트, purge 사전 검증 | PG 5 PASS (전체 1211 PASS) | SUCCESS (5/5) | [#189](https://github.com/ai-career-platform/ai-career-platform/pull/189) | PARTIAL | 물리 삭제(purge)·보존 기간 미승인, T83 감사 승인 |
| T88 | 격리 성능 기준선 스크립트·결과(7 API, 동시성 1~32, AI Mock) | 단위 7 PASS, 기준선 측정 완료 | SUCCESS (5/5) | [#190](https://github.com/ai-career-platform/ai-career-platform/pull/190) | PARTIAL | 성능 목표 미승인, T43·T56 미병합 |
| T89 | 접근성 회귀 35건(19개 화면), Chrome·Edge 실제 점검 | Vitest 385 PASS, 브라우저 PASS | SUCCESS (4/4) | [#191](https://github.com/ai-career-platform/ai-career-platform/pull/191) | PARTIAL | 스크린리더·Firefox·Safari NOT_RUN |
| T90 | 릴리스 Gate·시험 매트릭스·Runbook, 백업·복원 훈련 | 격리 복원 PASS | SUCCESS (6/6) | [#192](https://github.com/ai-career-platform/ai-career-platform/pull/192) Draft | **NO_GO** | 개인정보 purge 없음, Staging 0002·0003 미적용(#178), React 미배포 |
| T91 | MVP 이후 범위 기준선(PROPOSED), 변경 영향 매트릭스, 상태 스냅샷 | 스냅샷 재생성 동일 | SUCCESS (3/3) | [#193](https://github.com/ai-career-platform/ai-career-platform/pull/193) Draft | PARTIAL (PROPOSED) | PM 승인, T90 NO_GO |
| T92 | 사용자 여정·내비게이션 게이트 시험, 최소 UI 수정 2건 | 여정 8 PASS, Vitest 358 PASS | SUCCESS (4/4) | [#194](https://github.com/ai-career-platform/ai-career-platform/pull/194) | PARTIAL | 가입·계정 복구 화면 없음, Staging React 미배포 |
| T93 | 비밀번호 재설정 API(확정 계약), 메일 어댑터(Unavailable/Mock) | 단위 14·PG 5 PASS (전체 1225 PASS) | SUCCESS (5/5) | [#195](https://github.com/ai-career-platform/ai-career-platform/pull/195) Draft | PARTIAL | 메일 공급자 미정(요청 API 503 = HOLD), 이메일 인증 계약 없음 |
| T94 | 계정 복구 화면 `/password-reset`(Mock), HTTP Adapter 준비 | 13 PASS, Vitest 363 PASS | SUCCESS (4/4) | [#196](https://github.com/ai-career-platform/ai-career-platform/pull/196) Draft | FRONTEND_MOCK=PASS / REAL_API=HOLD | T93 미병합 |
| T95 | 알림 계약·수신 설정 매트릭스·OpenAPI 제안 | 계약 16 PASS | PR 본문 | [#197](https://github.com/ai-career-platform/ai-career-platform/pull/197) Draft | PARTIAL (PROPOSED) | 1차 범위 제외, 메일 공급자·법무 |

로컬 시험 환경: Windows 11, Python 3.12.10, Node 24, PostgreSQL 18.6 일회용 클러스터(루프백, 시험 후 삭제).

- Windows에서는 문서 저장소 POSIX 의존 시험(기존 20건 + T86 업로드 12건)이 실패·오류를 냅니다. 이 결과를 PASS로 세지 않았습니다.
- 위 시험은 Linux CI에서 실행·통과했습니다.

## 2. 증빙 구분

| 구분 | 일감 |
|---|---|
| 실제 PostgreSQL(격리) | T87, T88, T90(복원), T93 |
| Mock HTTP·Mock Adapter | T89(화면), T92, T94, T85 연계 |
| 실제 브라우저(Chrome·Edge, Mock 서버) | T89 |
| Staging 읽기 전용(GET) | T90: `/api/version` = main HEAD, Health 200 |
| 문서·제안(PROPOSED) | T91, T95, T93 §6(이메일 인증) |
| NOT_RUN | 스크린리더, Firefox·Safari, 실제 메일, 실제 AI 추론, Staging 실제 백업 복원·실행 중 digest, 운영 |

## 3. 발견 사항

| ID | 일감 | 심각도 | 내용 | 상태 |
|---|---|---|---|---|
| F87-1 | T87 | Medium | 탈퇴 접수·동의 철회가 감사 기록에 남지 않음 | T83 승인 대기, 시험으로 고정 |
| F87-2 | T87 | Low | 탈퇴 접수 후 본인이 처리 상태를 재조회할 수 없음 | T95 영수증 메일과 연계 제안 |
| G3·G7·G8 | T90 | **P0** | purge 없음, Staging 스키마 불일치(0002 없으면 탈퇴 접수 실패 예상), React 미배포 | NO_GO |
| J-1 | T92 | — | 목표 직무·경력·저장한 공고 진입점 없음 | **수정** |
| J-2 | T92 | — | 중첩 `<main>` 랜드마크 | **수정** |
| J-3 | T92 | — | 가입·비밀번호 찾기 링크 404 | 비밀번호 찾기는 T94가 해결(병합 순서 주의), 가입 화면은 미정 |
| P-1 | T88 | — | 처리량 포화(동시성 4~8)는 단일 Python 프로세스 때문, `/me` 요청당 SQL 5회, `ILIKE` 확장성 | 제안(N-08·N-09) |
| (참고) | T87·T93 | — | 최소 권한 확인에서 드러난 실제 필요 권한: 문서 행 잠금은 `user_documents` UPDATE, 분석 요청은 `model_versions` INSERT, 로그인은 `users`·`auth_sessions` 쓰기 | T07 권한 설계 참고 |
| (공정) | T88 | — | 첫 커밋의 가드 시험이 `.env`의 DB 이름과 같은 문자열을 썼음(공개된 이름, 비밀 아님) → 중립 이름으로 교체(`8011b13`). 이후 비밀값 검사 실패 시 커밋하지 않도록 절차 수정 | 해결 |

Critical 0, High 0 (T86 기준 유지).

## 4. 의존성·병합 순서 메모

- T94(#196)는 T93(#195)이 병합된 뒤 실제 API로 전환합니다.
- T92(#194)의 내비게이션 게이트는 `/password-reset`을 "알려진 끊긴 링크"로 고정하고 있습니다. #196이 먼저 병합되면 #194 쪽 목록에서 지워야 하고, 반대 순서면 #196에서 정리합니다.
- T87(#189)의 공용 fixture `disposable_pg`가 병합되면, T93 PG 시험의 자체 fixture를 그것으로 바꿀 수 있습니다.
- T90 Gate는 T87~T89 병합 후 재판정합니다.

## 5. PM 결정 필요

1. 개인정보 보존 기간(D-06)과 purge 작업 승인 → T87 시험 5를 실작업으로
2. Staging Migration 기준선 #178 승인·적용
3. React 앱 Staging 배포 시점
4. 성능 합격 기준(T88 제안: c=8 p95 < 100 ms, 오류 0)
5. T91 KEEP/DEFER/DROP/NEW 분류 승인
6. 메일 공급자, 비밀번호 재설정 요청 한도 값, 이메일 인증 계약
7. 알림 범위(1차 제외 해제 여부), 신규 동의 코드 3개, 마케팅·보존 법무 검토
8. T83 감사 계약(개인정보 이벤트 기록)
9. 접근 로그 쿼리 문자열(T86 F-1) 배포 설정 PR

## 6. 변경하지 않은 것

Staging·운영 설정, 공유 DB, Auto-CD, Migration 작성·적용(T93 포함), 실제 이메일·SMS, 실제 회원 데이터, GitHub 보호 규칙. Staging에는 T90에서 읽기 전용 GET 4회만 보냈습니다.
