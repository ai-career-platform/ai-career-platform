# T117 검증 보고서 — 핵심 UX 실제 사용자 시나리오(브라우저 E2E)

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=PARTIAL**
> - 실제 Chrome으로 같은 시나리오를 **Mock 모드**와 **실제 API 모드**에서 따로 돌렸습니다.
> - 실제 API 모드는 로컬 Backend + 일회용 PostgreSQL 18.6입니다. **Staging E2E는 아닙니다(NOT_RUN).**
> - 선행 T109(LLM 평가)가 시작되지 않아 AI 출력 시나리오는 HOLD입니다.

## 1. 목적과 선행

대표 사용자 역할별로 탐색 → 프로필 → 추천 → 공고 저장·지원 흐름을 실제 브라우저로 검증합니다.

| 선행 일감 | 상태 | 영향 |
|---|---|---|
| T92 사용자 여정 | 병합 | 여정 문서·게이트 시험 기준 |
| T100 고급 검색 | 병합(플래그 뒤) | 기본 공고 목록으로 시험 |
| T103 지원 현황 | 병합(Mock 플래그) | 실제 API 모드에서는 꺼짐 → 범위 밖 |
| **T109 LLM 평가** | **NOT_STARTED** | 추천 설명·AI 출력 품질 시나리오 HOLD |

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `frontend/e2e/t117-scenarios.mjs` (신규) | 시나리오 실행기. playwright-core와 Chrome 경로는 환경변수로 받습니다(저장소 의존성·잠금 파일 변경 없음, T118 SBOM 영향 없음) |
| `docs/testing/t117/e2e-mock-result.json`, `e2e-real-local-result.json` (신규) | 실행 결과(단계별 PASS·FAIL·NOT_RUN, 소요 시간). 계정 정보 없음 |
| `docs/testing/T117_VALIDATION_REPORT.md` (신규) | 이 문서 |

## 3. 시나리오 (데스크톱 1280px, 모바일 375px 각각)

| ID | 역할 | 단계 |
|---|---|---|
| A | 비로그인 → 구직자 | 홈 → 공고 목록 → **뒤로·앞으로** → 보호 화면 **직접 URL** → 로그인 화면 → 로그인 후 **원래 화면으로 복귀** → 새로고침 후 세션 유지 여부 기록 |
| B | 구직자 | 직무 탐색, 나의 기술, 맞춤 추천, 채용시장 추세, 저장한 공고(빈 상태), 목표 직무. 앱 안 이동, 제목 확인, 404·로그인 화면 아님, **가로 넘침 없음**, 화면 오류 알림 수집 |
| D | 역할 | 구직자가 관리자 화면 주소 → 접근 불가 / 관리자 로그인 → 관리자 화면 |
| C | 키보드 | 첫 Tab = "본문으로 바로가기", Enter → `#main-content` |
| E | 느린·실패 응답(**실제 API 모드만**) | 공고 API 2.5초 지연 → "불러오는 중" 표시 후 내용 / 503 → "다시 시도" → 복구 |

## 4. 결과

| 모드 | 환경 | PASS | FAIL | NOT_RUN |
|---|---|---|---|---|
| **Mock** | Vite dev(`VITE_API_MOCK=true`, 관리자 감사 화면 Mock 플래그) | **30** | 0 | 2(E: Mock Adapter는 네트워크를 쓰지 않음) |
| **실제 API(로컬)** | Vite dev → 프록시 → uvicorn `app.main` → 일회용 PG(migration 0001~0003 + seed + 합성 동의 정책 3개), 합성 계정 2개(구직자·관리자 역할) | **34** | 0 | 0 |

- 실제 API 모드 서버 로그: 요청 84건(`/auth/refresh` 20, `/job-roles` 13, `/me` 12 등), **5xx 0건**
- 화면 오류 알림(`role=alert`)은 두 모드 모두 0건이었습니다.

### 발견 사항

| ID | 내용 | 판단 |
|---|---|---|
| E-1 | **Mock 모드는 새로고침하면 로그인이 풀립니다**(Mock 세션이 메모리에만 있음). 실제 API 모드는 refresh 쿠키로 "내 계정"이 그대로 유지됩니다 | Mock 한계로 기록. 처음 실행 때 전체 이동(`goto`)을 쓴 단계 6건이 이것 때문에 실패했고, 시나리오를 메뉴 이동과 같은 앱 안 이동으로 바꿔 다시 돌렸습니다. 실패를 숨긴 것이 아니라 시험 방법을 바로잡은 것이며, 첫 실행 결과도 여기에 남깁니다 |
| E-2 | 실제 API 모드에서 관리자 감사 화면(`/admin/audit-events`)은 404입니다. 화면 플래그가 Mock 모드 전용(T84)이기 때문입니다 | 설계대로. 관리자 실제 API 화면 E2E는 플래그 승인 후 |
| E-3 | 느린 응답(2.5초)에서 "불러오는 중"이 데스크톱·모바일 모두 표시됩니다. 503에서는 "다시 시도"가 나오고 복구됩니다 | PASS |
| E-4 | 프로필 편집·공고 저장·지원 기록 쓰기 흐름은 이번 시나리오에서 실행하지 않았습니다(읽기 위주) | 후속: 쓰기 시나리오 추가 |

## 5. 재현

```bash
# Mock
VITE_API_MOCK=true VITE_ADMIN_AUDIT_UI=true npx vite --port 5196
E2E_BASE_URL=http://127.0.0.1:5196 E2E_MODE=mock PLAYWRIGHT_CORE=<path> CHROME_PATH=<chrome> node e2e/t117-scenarios.mjs

# 실제 API(로컬): 일회용 DB에 migration+seed, uvicorn app.main:app --port 8017,
# VITE_API_MOCK=false DEV_API_PROXY_TARGET=http://127.0.0.1:8017 npx vite --port 5195
E2E_BASE_URL=http://127.0.0.1:5195 E2E_MODE=real E2E_SEEKER=<합성> E2E_ADMIN=<합성> E2E_PASSWORD=<합성> … node e2e/t117-scenarios.mjs
```

- CI에는 넣지 않았습니다. Runner에 브라우저가 없고, 저장소 의존성을 추가하지 않았습니다.
- 일회용 DB(`t117_e2e`)와 서버는 실행 뒤 지웠습니다.

## 6. NOT_RUN / 후속
1. **Staging E2E**(실제 배포 이미지·Nginx): 접속 승인 필요
2. AI 출력 시나리오: T109 선행 필요
3. 쓰기 흐름(프로필 편집, 공고 저장, 지원 기록), 스크린리더 낭독, Firefox·Safari
4. CI 도입 여부(브라우저 설치 비용·의존성 추가는 T118 정책에 따름)
