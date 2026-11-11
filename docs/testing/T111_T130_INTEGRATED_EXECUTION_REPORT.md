# T111~T130 통합 실행 보고서

## 후속 상태 갱신 — PR 병합 결과 (2026-11-11)

아래 A~F절의 `Draft 20개·Merge 0개` 표시는 **SORNET 실행 완료 시점 스냅샷**입니다. GPT-Web의 순차 검토 및 충돌 해결 후, `main`에 **T111~T119 9건과 T121~T130 10건, 총 19건이 병합**됐습니다. 마지막 T120(#227)은 이 기록 작성 시점에 미병합 상태입니다.

- 재평가 대상 main SHA: `63697cfb851bc86d2de680df36b22e9de6dc4399` (#222/T130 병합)
- 운영 기반: #209 → #207 → #211 → #217 → #212 → #208 → #216 → #226 → #225 병합
- 정책/데이터: #210 → #213 → #214 → #215 병합. 정책 문서 `PROPOSED` 유지
- 기업·포트폴리오 API·UI: #218 → #220 → #219 → #221 → #224 → #222 병합. 서버 플래그 `COMPANY_ACCOUNTS_API`, `COMPANY_POSTINGS_API`, `PUBLIC_PORTFOLIO_API`는 기본 `false`; 화면은 Mock 모드 전용
- 공통 충돌 해결: T111 환경 계약과 `.env.example`/환경 매트릭스에 위 3개 서버 플래그 추가, T112 관측 미들웨어 및 기존 서버/화면 경로 보존
- PR 최신 HEAD의 CI는 병합 전 통과를 확인. 재평가 시점 최종 main CI는 **IN_PROGRESS**로, 최종 결과를 PASS라 주장하지 않음
- T120 릴리스 Gate는 **NO_GO 유지**: Staging DB migration 불일치 및 미승인 정식 migration(E5), Starlette HIGH 3건 등을 포함한 취약점 잔존(E6)
- T118 의존성 상향(#212)은 main 반영됨. **기존 'main 30건'은 이력 값이며**, 변경 후 보고서의 pip-audit 7건은 해당 시점 스캔 결과. 새로운 스캔을 수행하지 않았으므로 현 시점 숫자를 독립 재검증했다고 주장하지 않음
- Staging·운영·공유 DB·Secret·Auto-CD 실제 변경/실행 **없음**. T120 병합은 릴리스 승인이나 기능 활성화와 무관

---


> 실행 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · 기술 코디네이터 GPT-Web
> - main 시작·종료: `ab567656eabb06d86e4cf9966c3bdfd042da8318`(실행 중 main 변경 없음)
> - **PR 20개를 만들었고 병합한 PR은 없습니다.** 모두 Draft이고, 모든 PR에 Crasnec 리뷰를 요청했습니다.
> - 이 보고서는 T120 PR(#227)에 후속 커밋으로 넣었습니다. 이 커밋 이후 T120 PR의 CI를 다시 확인했습니다(§B).

## A. 전체 요약

| 항목 | 값 |
|---|---|
| 대상 | 20개(T111~T130) |
| PR 생성 | **20개**(#207~#222, #224~#227). #223은 다른 개발자의 PR(T74) |
| Draft | 20개 |
| DELIVERY_STATUS | PARTIAL 20 / PASS 0 |
| INTEGRATION_STATUS | HOLD 14 · PARTIAL 1(T117) · FAIL 2(T118 게이트, T120 판정 NO_GO) · NOT_RUN 1(T116) · (T121·T125·T128은 정책 HOLD에 포함) |
| 실패한 작업 | 없음(만들지 못한 PR 없음). 판정 결과로서 FAIL은 T118 취약점 게이트와 T120 NO_GO |
| 변경 파일 | 일감별 고유 변경 합 **129개**(스택 공통분 제외, 통합 보고서 포함) |
| 운영 변경 | Staging·운영·공유 DB·Secret·Auto-CD **변경 0**, Staging 접속 0회, 실제 메일 0건 |

## B. 작업별 결과

| Task | PR | Delivery | Integration | 시험(로컬) | CI(최신 HEAD) | Blocker |
|---|---|---|---|---|---|---|
| T111 환경·Secret | [#207](https://github.com/ai-career-platform/ai-career-platform/pull/207) | PARTIAL | HOLD | 33 PASS, backend 1184 | SUCCESS 5/5 | PM 검토, Staging 실검사, jungseop 브랜치 통합 결정 |
| T112 관측 | [#208](https://github.com/ai-career-platform/ai-career-platform/pull/208) | PARTIAL | HOLD | 24 PASS(T86 F-1 갱신 포함) | SUCCESS 5/5 | Nginx·로그 설정 승인, 재설정 토큰 Proxy 로그(F-1) |
| T113 장애 대응 | [#216](https://github.com/ai-career-platform/ai-career-platform/pull/216) | PARTIAL | HOLD | 27 PASS(실제 앱 DB 장애·복구) | SUCCESS 5/5 | #208, 채널·당번·예산 |
| T114 백업·복원 | [#211](https://github.com/ai-career-platform/ai-career-platform/pull/211) | PARTIAL | HOLD | 26 PASS(격리 PG 6) | SUCCESS 8/8 | 스케줄·역할·암호화 승인 |
| T115 Migration 게이트 | [#217](https://github.com/ai-career-platform/ai-career-platform/pull/217) | PARTIAL | HOLD | 15 OK(격리 PG 리허설 2) | SUCCESS 6/6(게이트 problems=0) | 헤더 규칙·Staging 절차 승인 |
| T116 API 호환 | [#209](https://github.com/ai-career-platform/ai-career-platform/pull/209) | PARTIAL | NOT_RUN | 37 PASS, 이력 재현 7건 검출 | SUCCESS 5/5(breaking 0) | 버전 정책 승인 |
| T117 E2E | [#225](https://github.com/ai-career-platform/ai-career-platform/pull/225) | PARTIAL | PARTIAL | Mock 30 PASS·실제 로컬 API 34 PASS | SUCCESS 4/4 | Staging E2E 승인, T109 미착수 |
| T118 SBOM·취약점 | [#212](https://github.com/ai-career-platform/ai-career-platform/pull/212) | PARTIAL | **FAIL**(게이트) | 29 PASS, backend 1321(상향 버전) | SUCCESS 5/5 | **starlette HIGH 3**(FastAPI 업그레이드 또는 예외 승인), 컨테이너 스캔 NOT_RUN |
| T119 품질 점검 | [#226](https://github.com/ai-career-platform/ai-career-platform/pull/226) | PARTIAL | HOLD | 16 PASS(격리 PG 1) | 아래 최종 블록 참고 | 실측 기준선 없음, T105 미착수 |
| T120 릴리스 판정 | [#227](https://github.com/ai-career-platform/ai-career-platform/pull/227) | PARTIAL | **FAIL**(NO_GO) | 4 PASS | 아래 최종 블록 참고 | P0 E5·E6, PM 승인 |
| T121 기업 역할 | [#210](https://github.com/ai-career-platform/ai-career-platform/pull/210) | PARTIAL | HOLD | 21 PASS | SUCCESS 5/5 | PM D-1~D-8, 법무 D-5 |
| T122 기업 데이터 | [#213](https://github.com/ai-career-platform/ai-career-platform/pull/213) | PARTIAL | HOLD | 14 PASS(격리 PG 10) | SUCCESS 8/8 | #210, PM D-1~D-5 |
| T123 기업 초대 API | [#218](https://github.com/ai-career-platform/ai-career-platform/pull/218) | PARTIAL | HOLD | 21 PASS(메모리 저장소), backend 1197 | SUCCESS 8/8 | 스택, migration·DB 저장소 |
| T124 기업 콘솔 UI | [#221](https://github.com/ai-career-platform/ai-career-platform/pull/221) | PARTIAL | HOLD(Mock PASS) | 15 PASS, vitest 491, Chrome | SUCCESS 9/9 | 스택, 실제 API |
| T125 공고 정책 | [#214](https://github.com/ai-career-platform/ai-career-platform/pull/214) | PARTIAL | HOLD | 20 PASS | SUCCESS 5/5 | #210, 법무 D-4 |
| T126 공고 API | [#220](https://github.com/ai-career-platform/ai-career-platform/pull/220) | PARTIAL | HOLD | 21 PASS(메모리 저장소), backend 1238 | SUCCESS 8/8 | 스택(+#214 병합), migration |
| T127 공고 콘솔 UI | [#224](https://github.com/ai-career-platform/ai-career-platform/pull/224) | PARTIAL | HOLD(Mock PASS) | 13 PASS, vitest 505(간헐 1/7), Chrome | SUCCESS 9/9 | 스택(+#220 병합), 실제 API |
| T128 공개 프로필 정책 | [#215](https://github.com/ai-career-platform/ai-career-platform/pull/215) | PARTIAL | HOLD | 15 PASS | SUCCESS 5/5 | #210, 법무 문구 |
| T129 포트폴리오 API | [#219](https://github.com/ai-career-platform/ai-career-platform/pull/219) | PARTIAL | HOLD | 25 PASS(메모리 저장소), backend 1212 | SUCCESS 5/5 | 스택, migration |
| T130 포트폴리오 UI | [#222](https://github.com/ai-career-platform/ai-career-platform/pull/222) | PARTIAL | HOLD(Mock PASS) | 11 PASS, vitest 487, Chrome | SUCCESS 6/6 | 스택, 실제 API |

시험 결과에 관한 공통 사항:
- 로컬 전체 Backend 실행에서는 매번 같은 기존 Windows 전용 실패·오류 32건(`test_documents.py`, `security/test_security_upload.py`)이 나옵니다. **PASS로 세지 않았고**, Linux CI에서는 통과합니다.
- T115의 기존 runner 시험 4건은 로컬 Windows에서만 실패합니다(main 기준 트리도 같음).

## C. 의존성(스택)

```
main ─┬─ T111 #207 ─ T112 #208 ─ T113 #216      (T113만 T112 위)
      ├─ T114 #211 · T115 #217 · T116 #209 · T117 #225 · T118 #212 · T119 #226 · T120 #227   (독립)
      └─ T121 #210 ─┬─ T122 #213 ─ T123 #218 ─┬─ T124 #221 ─┐
                    │                          └─────────────┼─ T126 #220 (+ T125 병합) ─┐
                    ├─ T125 #214 ──────────────────────────────┘                           │
                    │                                            T127 #224 = T124 + T126 병합 ┘
                    └─ T128 #215 ─ T129 #219 ─ T130 #222
```

- 두 선행 일감에 의존하는 T126·T127은 **병합 커밋**으로 합쳤습니다. 커밋을 복사하지 않았습니다.
- 스택 PR의 base는 모두 `main`입니다. 아래 PR이 병합되기 전에는 그 커밋이 diff에 함께 보이고, 병합되면 빠집니다(squash 병합이면 rebase가 필요할 수 있음).

## D. 병합 권장 순서와 주의

1. **독립 운영 기반**: #209(T116) → #207(T111) → #211(T114) → #217(T115) → #212(T118) → #208(T112) → #216(T113) → #226(T119) → #225(T117)
2. **기업·포트폴리오 정책**(PM·법무 승인 후): #210(T121) → #213(T122)·#214(T125)·#215(T128)
3. **서버**(플래그 꺼짐 유지): #218(T123) → #220(T126) / #219(T129)
4. **화면**(Mock 플래그): #221(T124) → #224(T127) / #222(T130)
5. **판정**: #227(T120). 다른 PR이 병합되면 Gate 결과를 다시 판정합니다.

| 주의 | 내용 |
|---|---|
| 공통 파일 충돌 | `backend/app/core/config.py`·`main.py`: T123·T126·T129가 플래그를 한 줄씩 추가합니다. `frontend/src/routes.tsx`·`env.ts`·`AppLayout.tsx`·a11y 회귀·여정 시험: T124·T127·T130이 겹칩니다. 나중에 병합하는 쪽에서 모두 유지해야 합니다 |
| **T111 계약 시험** | #207을 먼저 병합하면 Backend가 읽는 환경변수 = 계약 목록 시험 때문에, T123·T126·T129 병합 시 `COMPANY_ACCOUNTS_API`·`COMPANY_POSTINGS_API`·`PUBLIC_PORTFOLIO_API`를 `env_contract.py`에 추가해야 합니다(빠지면 시험 실패) |
| T116 오류 코드 기준선 | 새 오류 코드를 추가하지 않았습니다(409는 `CONFLICT` 하나). 확정 OpenAPI는 변경하지 않았습니다 |
| T118 의존성 상향 | PyJWT 2.15.0, python-multipart 0.0.31, pytest 9.0.3. 다른 PR의 CI는 기존 버전으로 돌았습니다. #212 병합 후 재실행을 권장합니다 |
| 승인 안 된 계약 활성화 | **없음**. 서버 플래그(`COMPANY_ACCOUNTS_API`, `COMPANY_POSTINGS_API`, `PUBLIC_PORTFOLIO_API`)는 기본 꺼짐이고, 켜도 저장소가 없어 503입니다. 화면은 Mock 모드 전용 플래그 뒤에 있습니다 |
| 정식 Migration | **없음**. 새 표는 `database/proposed/`(T122)와 정책 문서(T125·T128)의 제안뿐입니다 |
| 릴리스 | **NO_GO**(T120). P0는 E5(Staging migration 불일치·새 표 migration 없음)와 E6(main 의존성 CRITICAL·HIGH)입니다 |

## E. 주요 발견

| ID | 일감 | 심각도 | 내용 | 상태 |
|---|---|---|---|---|
| S-1 | T118 | **Critical/High(보고 기준)** | main 의존성 pip-audit 30건(PyJWT CRITICAL 1·HIGH 5, python-multipart HIGH 2, starlette HIGH 3). 코드 검토상 PyJWT·starlette HIGH는 경로가 닿지 않는 것으로 판단했고, 재현 시험은 없습니다 | 수정 PR #212, starlette는 승인 대기 |
| O-1 | T112 | Medium | 비밀번호 재설정 토큰(`?token=`)과 감사 API 사용자 ID가 접근 로그에 남음 | uvicorn 쪽 해결(#208), Nginx 제안. T123은 초대 토큰을 fragment로 전달 |
| A-1 | T116 | Info | 이력 재현에서 기록 없는 파괴적 계약 변경 7건(#166 CSRF 헤더, #139) | 예외 기록 절차 도입 |
| R-1 | T111 | Info | JWT 회전 시 refresh 세션은 유지되어 401 뒤 자동 복구, 목록 cursor는 무효 | Runbook |
| E-1 | T117 | Info | Mock 모드는 새로고침하면 로그인이 풀리고, 실제 API는 유지됨 | 시나리오를 앱 안 이동으로 |
| U-1 | T124 | Low | 초대 전송 후 키보드 포커스가 body로 빠짐 | Chrome 확인 중 발견·수정 |

## F. 하지 않은 것

- PR 병합, Staging·운영 배포, Auto-CD 정책 변경
- 공유 DB 스키마 변경, migration 적용(일회용 DB 제외), Secret 조회·회전
- 운영 알림·실제 메일 발송, 실제 개인·기업 데이터 사용
- Staging 접속(0회)
- 일회용 DB(`t114_*`, `t115_*`, `t117_e2e`, `t119_q`)와 dev 서버는 실행 후 지웠습니다.
