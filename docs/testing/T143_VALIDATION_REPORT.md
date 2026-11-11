# T143 검증 보고서 — 내 데이터 내려받기·요청 이력 화면 (Mock 전용)

## 1. 작업 목적
반출 신청, 처리 대기·완료·실패·만료 표시, 요청 이력, 재인증, 오류 후 재시도를 보여 주는 화면을 만듭니다. T141 정책과 T142 서버가 승인 전이라 **Mock 모드 전용 플래그 뒤**에 둡니다.

## 2. 기존 구현·PR 재사용
- **T130 패턴**: ServiceProvider + context + 메모리 Mock Adapter, `useQuery().setData`로 포커스를 지키며 갱신, 공용 `ConfirmDialog`(포커스 이동·Tab 순환·Esc·포커스 복귀), `StatePanel`
- **Mock 로그인**: `MOCK_PASSWORD`를 재인증 비밀번호로 그대로 사용
- **T89·T92 시험에 추가**: `/me/data`를 접근성 회귀 목록에 넣었고, 진입점은 메뉴 링크입니다(여정 게이트 통과).
- **T31 탈퇴**: 이력에 함께 보이고, 관리는 기존 개인정보 화면으로 안내합니다.

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- 스택: T142 `task/t142-personal-data-request-api`(#235) → T141 #230 위
- HEAD_SHA: PR 댓글에 기록

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `frontend/src/api/personalData.ts` | 타입·라벨·서비스 인터페이스(T141/T142 기준) |
| `frontend/src/mocks/personalData.ts` | Mock Adapter: 재인증 10분, 409, 처리·실패·재시도, 1회 다운로드, 24시간 만료, 사용자 격리 |
| `frontend/src/personal/PersonalDataServiceProvider.tsx`, `personalDataContext.ts` | 데이터 경로(Mock만) |
| `frontend/src/pages/MyDataPage.tsx`, `MyDataPage.css` | 화면 |
| `frontend/src/pages/MyData.test.tsx` | 14건 |
| `frontend/src/config/env.ts` | `personalDataUi` = Mock 모드 && `VITE_PERSONAL_DATA_UI` |
| `frontend/src/routes.tsx`, `frontend/src/layouts/AppLayout.tsx` | `/me/data` 경로·메뉴(플래그 뒤) |
| `frontend/src/a11y/AccessibilityRegression.test.tsx` | `/me/data` 점검 추가 |

## 5. 선행조건
| 일감 | 상태 |
|---|---|
| T20·T32 | 병합(공통 레이아웃·개인정보 설정 화면) |
| T142 | **#235 미병합**, 플래그 뒤·저장소 없음 |
| T141 | **#230 미병합(PROPOSED)** |

## 6. 실제 실행 명령
```bash
cd frontend
npm run lint                 # oxlint --deny-warnings → 0
npx tsc -b --noEmit          # 0
npx vitest run               # 전체
npm run build
VITE_API_MOCK=true VITE_PERSONAL_DATA_UI=true npx vite --mode mock --port 5201
node <scratchpad>/t143_shots.cjs 5201     # Chrome(playwright-core), 1280px·375px
```

## 7. 정상·오류·권한 검증
**Vitest 14건(MyData.test.tsx)**
- **플래그**
  - 꺼짐: 메뉴 없음, 경로 404
  - 기본 라우트에 경로 없음, Mock 모드 필수, HTTP 어댑터 미연결
- **로그인**: 필요(비로그인 → 로그인 화면). 빈 이력 안내
- **재인증**
  - 요청 전 비밀번호 확인 창이 열리고 입력에 포커스
  - 틀린 비밀번호는 `role=alert` + `aria-invalid`로 알리고 창 유지
  - 맞으면 하던 동작을 이어서 진행
- **다운로드**
  - 10분 안이면 창 없이 진행
  - 저장된 파일 내용 확인: 합성 데이터, 금지 키 5종 없음
  - 받은 뒤 `만료됨`, 버튼 사라짐, 새 요청 가능
- **10분 경과**: 서버(Mock) 403 → 비밀번호 확인 창 → 확인 뒤 이어서 다운로드
- **24시간 경과**: `만료됨`, 다운로드 버튼 없음
- **취소**: 확인 창을 거쳐 `취소됨`
- **실패**: 사유(자동 재시도 3회 안내) → 서버 재시도 뒤 완료
- **오류**
  - 목록 불러오기 실패 → `다시 시도`
  - 다운로드 중 네트워크 오류 → `role=alert`, 상태 유지, 다시 누르면 성공
  - 브라우저 저장 실패 → "다시 받을 수 없으니 새로 요청" 안내(1회용이라)
- **격리**: 다른 사용자에게 내 요청이 안 보이고, 내 요청 취소를 시도하면 404
- **키보드**: Esc로 창을 닫으면 원래 버튼으로 포커스 복귀

**전체 Frontend**: Vitest **532 passed, 22 skipped**(42 파일), lint 0, tsc 0, build 성공

**Chrome(실제 브라우저, Mock)**: 데스크톱 1280px·모바일 375px
- 메뉴 노출
- 키보드만으로 요청 → 비밀번호 창(입력 포커스) → 오답 안내 → 정답 → 처리 대기 → 완료 → **실제 다운로드 이벤트** `my-data-export.json`(547 B, 형식 `ai-career-export/v1`, 금지 키 없음) → 만료됨
- 가로 넘침 없음
- `data-requests` 네트워크 요청 0건(Mock만)
- 스크린샷: `t143-{pending,ready,done}-{desktop,mobile}.png`(scratchpad, 저장소에 넣지 않음)

## 8. PostgreSQL / Mock / 실제 API 구분
| 구분 | 결과 |
|---|---|
| Mock(Vitest + Chrome) | PASS |
| 실제 API(T142) | **NOT_RUN**. 서버 플래그 기본 꺼짐·저장소 없음. 공용 `HttpClient`가 `X-Reauth-Token` 같은 사용자 지정 헤더를 지원하지 않아 실제 어댑터를 만들지 않았습니다 |
| PostgreSQL | 해당 없음 |
| Staging | NOT_RUN |

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- T141·T142 승인과 저장소 migration
- 실제 연결: `api/http.ts`에 요청별 헤더 지원 추가 → `createHttpPersonalDataService` 작성 → Provider 한 곳에서 교체
- 재인증 만료 판단: 화면은 브라우저 시계로 미리 판단하고, 최종 판단은 서버 403입니다(시계가 어긋나도 403 → 재확인 창으로 회복).

## 11. 후속 작업
- 실제 API 연결과 실제 서버 E2E(T117 시나리오 방식)
- 처리 완료 알림(T97 알림함)과 연동 검토
