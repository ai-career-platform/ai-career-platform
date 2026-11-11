# T140 검증 보고서 — 직무·기술 자동완성·용어 선택 UX

> **담당자 안내**
> - T140 담당은 **조영우(`cyw0927`)** 입니다. 이 PR은 담당자 작업을 대신하지 않는 **보완 제안**입니다.
> - 담당자의 이전 PR #33(`task/t140-skill-autocomplete`, PoC 화면 `poc/t140-autocomplete/`)은 2026-11-09 코멘트 없이 닫혔고, 병합되지 않았습니다. 이 PR은 그 브랜치를 건드리지 않습니다.
> - #33의 규칙(2~60자, 앞부분 일치 우선, 중복 선택 방지, 한글 IME 조합 중 보류, 키보드 선택)은 이 구현에 반영했습니다. #33이 남긴 "응답 지연·취소, 실제 접근성 검증"도 이번에 다뤘습니다.
> - 담당자가 이어서 진행한다면 이 PR을 기반으로 하거나 닫을 수 있습니다. 결정은 PM·담당자 몫입니다.

## 1. 작업 목적
기존 T34 "나의 기술" 화면의 검색 상자를 T139 자동완성(동의어 → 표준 코드)과 연결합니다.
- 화면 플래그 `VITE_SKILL_AUTOCOMPLETE`가 켜져 있을 때만 바뀝니다. 기본은 꺼짐입니다.
- 꺼져 있으면 기존 T17 이름 검색 동작이 **그대로**입니다.

## 2. 기존 구현·PR 재사용
- **T34 `MySkillsPage`(#146)를 재사용했습니다.** 새 화면이나 새 경로는 만들지 않았습니다.
  - 이미 있던 기능: ARIA combobox/listbox, `aria-activedescendant`, ↑↓·Enter·Esc, 디바운스, `useQuery` 요청 취소, 중복 방지, "추가됨" 표시
- T139 API(#238, 스택 base)를 씁니다.
- 정규화 함수 `normalizeSkillTerm`은 T137·T139와 같은 규칙입니다.
- T23 직무·기술 탐색(#148)은 T17 카탈로그 조회 화면이라 이번에 바꾸지 않았습니다. 직무 자동완성은 T139 범위 밖입니다.

## 3. BASE_SHA / HEAD_SHA
- BASE: `task/t139-skill-autocomplete-api` @ `dc69ed5` (main `822fa16` + T139)
- HEAD_SHA: PR 댓글에 기록합니다.

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `frontend/src/pages/MySkillsPage.tsx` | 플래그가 켜지면 `/v1/skills/suggest` 사용. 동의어로 찾은 경우 "‘파이썬’로 찾음", 다의어는 "여러 기술 중 골라 주세요" 표시. 등록 불가(skill_id 없음) 항목은 고를 수 없음. IME 조합 중 키 무시 |
| `frontend/src/api/catalog.ts`, `api/skills.ts` | `skills.suggest`, T139 응답 타입, `normalizeSkillTerm` |
| `frontend/src/mocks/skills.ts` | Mock `/v1/skills/suggest`. 합성 동의어, 다의어 `py`, 등록 불가 예시 `RUST` |
| `frontend/src/config/env.ts` | `skillAutocomplete` 플래그 |
| `frontend/src/pages/MySkillsPage.css` | 일치 표기 안내 스타일 |
| `frontend/src/pages/MySkillsSuggest.test.tsx` | 10건 |
| `docs/testing/t140/t140-{real,mock}-result.json` | Chrome 확인 결과. 계정 정보 없음 |

## 5. 선행조건
| 선행 | 상태 |
|---|---|
| T20 공통 UI | 병합 |
| T23 | 병합 |
| T34 | 병합 |
| T139 | **#238 OPEN**(이 PR의 base) |

## 6. 실제 실행 명령
```bash
cd frontend
npm run lint && npx tsc -b --noEmit && npx vitest run && npm run build
# Chrome (playwright-core + 설치된 Chrome)
VITE_SKILL_AUTOCOMPLETE=true npx vite --mode mock --port 5205              # Mock
DEV_API_PROXY_TARGET=http://127.0.0.1:8139 VITE_SKILL_AUTOCOMPLETE=true npx vite --port 5204   # 실제 API
#   Backend: uvicorn app.main:app --port 8139 (SKILL_AUTOCOMPLETE_API=true,
#            일회용 DB = migration 0001~0003 + T10 seed + 합성 동의 정책)
#   합성 계정은 실행마다 새로 가입(@example.invalid, 무작위 비밀번호, 기록 안 함)
```

## 7. 정상·오류·권한 검증
| 항목 | Vitest(Mock) | Chrome Mock | Chrome 실제 API |
|---|---|---|---|
| 한글 동의어 → 표준 기술(`파이썬` → Python) | PASS | PASS | 해당 없음. 실제 DB에 별칭 표가 없어 **빈 결과 안내**를 확인(PASS) |
| 영문 줄임말·대소문자(`K8S`), 한 음절(`도` → Docker ‘도커’) | PASS | PASS(`K8S`) | — |
| C++ / C# 구분 | 정규화 시험 PASS | — | PASS |
| ↓↑ 이동(순환), `aria-activedescendant`·`aria-selected`, Esc 닫힘(`aria-expanded=false`) | PASS | PASS | PASS |
| 다의어 후보 모두 표시, 자동 선택 없음 | PASS | — | — |
| **IME 조합 중 Enter 무시**(`isComposing`, keyCode 229) → 조합 끝난 뒤 Enter 추가 | PASS | 해당 없음(헤드리스 Chrome은 실제 IME 조합 불가) | 해당 없음 |
| 중복 선택 방지(다른 표기로 찾아도 "추가됨"·aria-disabled, 클릭 시 안내) | PASS | PASS | PASS(저장 후 같은 계정) |
| 등록 불가 코드(skill_id 없음) 선택 불가 | PASS | — | — |
| 빈 결과·오류(503) 안내 | PASS | — | 빈 결과 PASS |
| **빠른 입력 시 늦게 온 이전 응답 무시** | PASS(취소를 무시하는 느린 서버 흉내) | — | — |
| 저장 후 새로고침해도 유지 | — | Mock은 탭마다 저장소 초기화(T117 E-1) | PASS(DB `user_skills` 행 확인) |
| 320~375px 가로 넘침 없음 | — | PASS(375) | PASS(375) |
| 비로그인 → 로그인 화면(기존 T34 시험) | PASS | — | — |
| 실제 API 호출 | — | — | `/skills/suggest` 12회, 모두 2xx, 옛 `/skills` 0회 |

전체 Frontend(Windows): lint 통과, `tsc -b` 통과, **Vitest 527 passed / 22 skipped**(main 대비 +10, skip 증가 없음), build 통과.

## 8. PostgreSQL / Mock / 실제 API 구분
- **Mock**: Vitest 10건, Chrome 12단계 PASS. 가상 동의어라 실제 서비스 PASS가 아닙니다.
- **실제 API(로컬 격리)**
  - 구성: uvicorn + 일회용 PostgreSQL 18.6(`t139_real`, 공유 DB 아님)
  - Chrome 14단계 PASS, 실제 저장 확인
  - 실제 DB에서는 동의어 변환이 되지 않습니다(T137 별칭 표 미적용, T139 HOLD와 같음).
- **Staging**: NOT_RUN

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- T139 #238 병합, 그리고 서버·화면 플래그 승인
- T137 별칭 표 migration: 실제 동의어 변환에 필요
- 담당자(조영우) 확인. 이 PR을 이어받을지 닫을지 결정 필요
- 실제 IME(한글 키보드) 수동 확인 NOT_RUN. 헤드리스 Chrome으로는 조합 입력을 재현할 수 없습니다.

## 11. 후속 작업
- 담당자 수동 확인: Windows·macOS 한글 IME, 화면 낭독기(NVDA·VoiceOver)
- 직무 자동완성: 직무 다의어 규칙 결정 후
- T23 탐색 화면에 같은 combobox 재사용 검토

```text
UNIT_TESTS=PASS
POSTGRESQL_TESTS=NOT_RUN (UI only; real API run used disposable PG via backend)
FRONTEND_TESTS=PASS
BROWSER_E2E=PASS (Chrome headless, mock 12/12 + local real API 14/14)
MOCK_VALIDATION=PASS
REAL_API_VALIDATION=PASS (local isolated; synonyms HOLD on real DB)
STAGING_VALIDATION=NOT_RUN
```
