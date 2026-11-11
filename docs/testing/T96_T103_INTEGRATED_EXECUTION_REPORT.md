# T96~T103 통합 실행 보고서

> 실행 2026-11-11 · 담당 문길래 · 실행 Claude Code · main 시작/종료 `ceee31d` (실행 중 main 변경 없음)
> **병합한 PR은 없습니다.** 모든 PR에 Crasnec 리뷰를 요청했습니다.
> 실행 중 main의 Frontend CI 실패를 발견해 별도 수정 PR(#199)을 냈습니다.

## 1. 결과 요약

| Task | 구현 | 로컬 시험 | PR | 상태 | 차단 요인 |
|---|---|---|---|---|---|
| T96 | 알림 발송 모듈: outbox·재시도·중복 방지·마스킹, 제안 DDL | 단위 21 + PG 7 PASS | [#198](https://github.com/ai-career-platform/ai-career-platform/pull/198) Draft | PARTIAL | 메일 공급자, 템플릿 승인, DDL 승인 |
| T97 | 알림함·수신 설정 화면(Mock 플래그) | 14 PASS, Chrome 1280/375 | [#200](https://github.com/ai-career-platform/ai-career-platform/pull/200) Draft | FRONTEND_MOCK=PASS / REAL_API=HOLD | 알림함 API 계약, T95 수신 설정 API |
| T98 | 고급 검색 계약(PROPOSED), 수용 사례 JSON | 계약 10 PASS(로컬 전용) | [#201](https://github.com/ai-career-platform/ai-career-platform/pull/201) Draft | PARTIAL (PROPOSED) | PM 승인 D-1~D-6 |
| T99 | 고급 검색 구현(플래그), 인덱스 제안, 10만 건 측정 | 단위 15 + PG 14 PASS | [#202](https://github.com/ai-career-platform/ai-career-platform/pull/202) Draft · T98 위 | PARTIAL | T98 승인, 인덱스 적용 절차 |
| T100 | 고급 검색 화면(Mock 플래그), URL 상태 | 38 PASS, Chrome 1280/375 | [#203](https://github.com/ai-career-platform/ai-career-platform/pull/203) Draft · T99 위 | FRONTEND_MOCK=PASS / REAL_API=HOLD | #199·#201·#202 |
| T101 | 지원 추적 계약(PROPOSED), 제안 DDL | 계약 9 PASS(일회용 PG 포함, 로컬 전용) | [#204](https://github.com/ai-career-platform/ai-career-platform/pull/204) Draft | PARTIAL (PROPOSED) | PM·법무 D-1~D-7 |
| T102 | 지원 기록 API(플래그) | 단위 61 + PG 8 PASS | [#205](https://github.com/ai-career-platform/ai-career-platform/pull/205) Draft · T101 위 | PARTIAL | T101 승인, 정식 migration |
| T103 | 지원 현황 보드(Mock 플래그) | 13 PASS, Chrome 1280/375 | [#206](https://github.com/ai-career-platform/ai-career-platform/pull/206) Draft · T102 위 | FRONTEND_MOCK=PASS / REAL_API=HOLD | #199·#204·#205 |
| (수정) | main Frontend CI 복구: T92 시험의 `/password-reset` 고정 해제 | Vitest 407 PASS | [#199](https://github.com/ai-career-platform/ai-career-platform/pull/199) Ready | — | 없음(먼저 병합 권장) |

전체 백엔드(로컬, Windows): T96 1223 · T99 1224 · T102 1264 passed. 매번 실패·오류 32건이 같은 목록으로 나옵니다.
- 32건은 기존 Windows 전용 문서 저장소 시험(POSIX 의존)이며, PASS로 세지 않았습니다.
- 같은 시험이 Linux CI에서는 통과합니다.

## 2. 증빙 구분

| 구분 | 일감 |
|---|---|
| 실제 PostgreSQL 18.6(일회용, 루프백) + 실제 FastAPI | T96, T99, T101(DDL), T102 |
| 합성 10만 건 성능·실행 계획 | T99 (로컬 전용, CI 아님) |
| Mock Adapter + 실제 라우터 | T97, T100, T103 |
| 실제 Chrome(Mock dev 서버) | T97, T100, T103 |
| 문서·제안(PROPOSED) | T98, T101 (`docs/` 시험은 CI가 실행하지 않음 → 로컬 결과) |
| NOT_RUN | 실제 메일 발송, 실제 잡코리아 데이터, 스크린리더·Firefox·Safari, HTTP 동시성 부하(검색), Staging·운영 |

## 3. 발견 사항

| ID | 일감 | 심각도 | 내용 | 상태 |
|---|---|---|---|---|
| M-1 | 공통 | **High(CI)** | T94 병합(`c641a8c`)부터 main Frontend CI 실패. 원인은 T92 시험이 `/password-reset`을 끊긴 링크로 고정했던 것(T87~T95 보고서 §4에서 예고) | #199 수정 |
| P-1 | T99 | Medium | 마감순 정렬이 무한대를 `CAST(:param AS timestamptz)`로 보내 식 인덱스를 못 씀(text→timestamptz 캐스트가 STABLE) | 코드 수정(SQL 상수), 권장 인덱스로 p95 124 → 1.6 ms |
| P-2 | T99 | — | `pg_trgm`은 C 로케일에서 한글 trigram을 만들지 않아 효과 없음, 고용형태·지역 인덱스도 10만 건에서 이득 없음 | 비권장으로 기록 |
| C-1 | T102 | — | 전용 409 코드(T101 D-7)는 확정 오류 코드 표·시험과 충돌 | 승인 전까지 `CONFLICT`, 원인은 서버 로그 |
| D-1 | T98 | — | 기술·경력·연봉·학력은 원천(잡코리아 정규화·DB)에 없음 | HOLD로 계약에 명시 |
| R-1 | T96 | — | worker 중단 시 최소 1회 전달 → 공급자 멱등 키 지원이 공급자 선정 조건 | 문서화 |

Critical 0, High 1(CI, 수정 PR 있음).

## 4. 병합 순서·스택

```
#199 (main CI 복구)  ─┬─ #200 T97 (base에 #199 포함)
                      ├─ #203 T100 = #201 T98 → #202 T99 → T100 (+#199 cherry-pick)
                      └─ #206 T103 = #204 T101 → #205 T102 → T103 (+#199 cherry-pick)
#198 T96 (독립)
```

- 스택 PR은 base가 main이라, 아래 PR이 병합되기 전에는 그 커밋들이 diff에 함께 보입니다. 아래 PR이 병합되면 자동으로 빠집니다.
- #202(T99)와 #205(T102)는 둘 다 `backend/app/core/config.py`·`main.py`에 기능 플래그를 추가합니다. 나중에 병합하는 쪽에서 두 줄을 모두 유지해야 합니다.
- #200(T97)과 #206(T103)은 둘 다 `routes.tsx`·`AppLayout.tsx`·`env.ts`·a11y 회귀에 플래그를 추가합니다. #203(T100)은 `routes.tsx`·`env.ts`·a11y 회귀를 건드립니다. 이것도 나중 병합 쪽에서 합칩니다.
- 이 스택 구조 덕분에 T100·T103의 Mock과 T99·T102의 실제 SQL이 **같은 계약 산출물**로 검증됩니다(T98 JSON, T101 이동 표).

## 5. PM·법무 결정 필요

1. 메일 공급자(멱등 키 지원), 알림 템플릿 승인, outbox 표 승인(T96)
2. 알림함 API 계약, T95 수신 설정 API·신규 동의 코드 3개(T97)
3. T98 D-1~D-6: 검색어에 기업명 포함, 다중 값 상한, 지역 파생 규칙, 기준 시점, pg_trgm, 기술·경력 HOLD 해제 조건
4. T99 권장 인덱스 1개의 정식 migration과 운영 `CREATE INDEX CONCURRENTLY` 절차(러너는 CONCURRENTLY 금지)
5. T101 D-1~D-7: 외부 공고, 북마크와 관계, 500건 상한, 처리 근거·보존(법무), 단계 이력, 일정 알림, 전용 409 코드
6. 기능 플래그 활성화 시점: `JOB_SEARCH_ADVANCED`, `JOB_APPLICATIONS_API`, 프런트 Mock 플래그 3개

## 6. 변경하지 않은 것

- Staging·운영 설정, 공유 DB, Auto-CD
- 정식 Migration 작성·적용: 새 표·인덱스는 모두 `database/proposed/`
- 실제 이메일·SMS(0건), 실제 회원 데이터, GitHub 보호 규칙
- Staging 접속(이번 실행 0회)
- 일회용 PostgreSQL 클러스터(scratchpad)는 시험 후 정지합니다.
