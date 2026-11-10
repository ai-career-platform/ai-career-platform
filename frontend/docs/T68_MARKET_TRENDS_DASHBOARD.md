# T68 — 채용시장 추세 대시보드 UI (UI-024, F-024, FR-ANL-005)

작업지시서: [docs/work-orders/remaining-30/T68.md](../../docs/work-orders/remaining-30/T68.md) · 계약: T65 [MARKET_METRICS_CONTRACT](https://github.com/ai-career-platform/ai-career-platform/pull/171) · API: T67 [PR #174](https://github.com/ai-career-platform/ai-career-platform/pull/174)

## 화면

경로 `/market-trends` (로그인 필요, 주 메뉴 "채용시장 추세"). T67 `GET /api/v1/market-trends`의 **관측값(`observations`)만** 그래프와 표로 보여준다. `forecasts`는 쓰지 않는다.

| 항목 | 구현 |
|---|---|
| 조회 조건 | 관측 지표(신규 게시 공고 수 / 기술 요구 비율), 집계 단위(일·주·월), 시작일·종료일, 직무(없으면 전체 시장), 기술(기술 요구 비율일 때 필수, 검색 후 선택) |
| 기간 검사 | 날짜 누락·시작일 > 종료일·구간 수 상한(일 366, 주 157, 월 60; T67 `MAX_POINTS`)은 화면에서 막고 요청하지 않음 |
| 그래프 | `components/MarketTrendChart.tsx` SVG 선 그래프(외부 라이브러리 없음). 관측 없는 구간은 **선을 끊고 0으로 채우지 않음**. 포인터·키보드(←/→, Home/End, Esc)로 구간 값 읽기 |
| 표 | 공통 `DataTable`. 그래프와 **같은 `observations` 배열**을 같은 순서로 표시 |
| 수치 표시 | `pages/marketTrendFormat.ts`: `count` → `1,234건`, `ratio`(0~1) → `71.43%`. API 값은 바꾸지 않고 표시 문자열만 만든다(그래프 `data-value`는 원본 값) |
| 지표 정의 | T65 계약 §1·§3 문구, 빈 구간 ≠ 0 설명 |
| 데이터 기준 | 출처 이름·코드, 조회 기간·단위(KST), 범위(직무·기술), 단위, 마지막 관측 구간 |
| 대표성 문구 | "본 통계는 수집된 채용공고를 기준으로 하며 전체 채용시장을 대표하지 않습니다." 항상 표시 |
| 상태 | 불러오는 중 / 데이터 없음(관측 없음 ≠ 0건) / 오류(401·404·422·네트워크·5xx 별도 문구, 401 외에는 다시 시도) |
| 경합 | 조건이 바뀌면 이전 요청을 취소하고 늦은 응답을 버림(`useQuery`) |
| 모바일 | 720px 이하 한 열, 그래프는 컨테이너 폭(ResizeObserver)에 맞춰 다시 그리고 X축 눈금 수를 줄임 |

타입은 `api/marketTrends.ts`에 T67 응답을 수기로 옮겼다. main의 `openapi.yaml` `MarketTrend`는 T67 이전 초안이므로, **#174 병합 후 `Schemas['MarketTrend']`로 바꾼다.** 이 PR은 OpenAPI·schema.gen·Backend를 바꾸지 않는다.

## 선행 의존성

| 일감 | PR | 상태 (2026-11-10) | T68 영향 |
|---|---|---|---|
| T65 지표 계약·migration 0003 | #171 | OPEN, 리뷰 대기 | 지표·단위·빈 구간 규칙. Staging에 0003 미적용 |
| T66 집계 job | #172 | OPEN, 리뷰 대기 | `market_observations` 적재 주체. Staging 미실행 |
| T67 조회 API | #174 | OPEN, main과 충돌(DIRTY) | 이 화면이 부르는 API. main·Staging에 없음 |

## Staging DB 읽기 전용 점검 (2026-11-10)

`.env` 접속 정보로 직접 연결, 세션을 `default_transaction_read_only=on`·`statement_timeout=15s`로 고정하고 카탈로그·집계 SELECT만 실행했다. 접속 계정이 SUPERUSER라 역할 수준의 SELECT 전용은 보장되지 않는다(작업지시서 §5 최소 권한 원칙 위반 상태, 별도 조치 필요).

| 항목 | 결과 |
|---|---|
| 접속 | PASS (PostgreSQL 18.1) |
| `career.market_observations` / `market_forecasts` / `data_sources` / `job_roles` | 모두 존재 |
| `market_observations` 행 수 | **0** (최초·최종 관측일 없음, 집계 단위·지표·직무별 관측 없음) |
| `market_forecasts` 행 수 | 0 |
| `data_sources` | 1건 `synthetic_seed` (T10 합성 Seed) |
| `job_roles` | 30건 |
| `job_postings` | 100건, 모두 `synthetic_seed` 출처, 게시일 2026-10-01~10-29 |
| T65 migration 0003 | **미적용** (`skill_id` 컬럼 없음, migration 기록 테이블 `career_migration.schema_migrations` 없음) |
| T67 관측 조회 SQL을 Staging에 실행 | `ERROR: column o.skill_id does not exist` → Staging DB에서 T67 API는 관측 조회 시 실패한다 |
| 배포된 Staging API (`:18080`, main `624f660`) | `/api/v1/market-trends` 라우트 없음 (404) |

## 검증

### 자동 테스트 (가상 응답, 실제 서비스 PASS 아님)

- `pages/marketTrendFormat.test.ts` — 표시 단위(T65 손 계산 값 71.43% 등), KST 주·월 구간, 구간 수 상한 경계, 빈 구간 끊기, 오류 문구
- `pages/MarketTrendsPage.test.tsx` — 기본 조회, 출처·기준 시점·대표성 문구, **그래프 표식 값 = API 원본, 키보드로 읽은 그래프 값 = 표 값**, 예측값 미표시, 직무·단위·기간·지표·기술 필터, 잘못된 기간(요청 없음), 빈 데이터, 503 재시도, 401·404·422·네트워크, 늦은 응답 경합, 접근성 이름, 모바일 폭(343px), 로그인 경유 라우트(Mock)

### 실제 Backend E2E (opt-in, 일회용 PostgreSQL)

Staging에는 관측 데이터가 없고 T67 API가 동작할 스키마도 아니므로, **실제 데이터 검산은 일회용 DB에서 했다.** main + #174(T67) + #172(T66) 로컬 통합 브랜치(push 안 함)의 Backend를 띄우고 T65 합성 fixture를 T66 job으로 집계했다.

```bash
# 1) 일회용 PostgreSQL에 0001~0003 + Seed + 합성 동의 정책(terms/privacy 2026-11) + database/market_metrics/t65_fixture.sql
# 2) T66 집계 (통합 브랜치 backend/)
python -m app.market_aggregation --source t65_fixture --period week  --as-of 2026-11-10T09:00:00+09:00 --backfill-from 2026-10-05
python -m app.market_aggregation --source t65_fixture --period month --as-of 2026-11-10T09:00:00+09:00 --backfill-from 2026-10-01
# 3) 통합 브랜치 Backend: APP_ENV=local-dev DATABASE_URL=<일회용 DB> uvicorn app.main:app --port 8068
# 4) 같은 DB의 관측값 스냅샷 (읽기 전용 SELECT)
PGOPTIONS="-c default_transaction_read_only=on" psql -X -At -f frontend/docs/t68_db_snapshot.sql <일회용 DB> > t68_db_snapshot.json
# 5) DB → API → 그래프·표 검산
T68_REAL_API_ORIGIN=http://127.0.0.1:8068 T68_DB_SNAPSHOT=t68_db_snapshot.json npx vitest run src/pages/MarketTrendsPage.integration.test.tsx
```

`MarketTrendsPage.integration.test.tsx`는 합성 사용자를 만들므로 loopback Backend + 일회용 DB에서만 실행한다.

| 조건 | DB 행 | API = DB (날짜·값·단위·출처·순서) | 그래프 표식 = 표 = DB |
|---|---|---|---|
| 전체 직무 주간 공고 수 10-05~11-08 | 7, 2, 0, 1, 2 | PASS | PASS |
| 백엔드 직무 주간 공고 수 | 5, 0, 0, 1, 1 | PASS | PASS |
| 전체 시장 PYTHON 주간 기술 요구 비율 | 10-05 0.7143 (71.43%) | PASS | PASS |
| 전체 직무 월간 공고 수 10월 | 10 | PASS | PASS |
| 백엔드 직무 월간 JAVA 기술 요구 비율 | 0.3333 (33.33%) | PASS | PASS |
| 관측 없는 직무 (AI 리서처) | 0행 → 200, `source=null`, 화면 빈 상태 | PASS | — |
| 없는 직무·기술·출처 404 / 역순 기간·기간 초과·기술 누락·날짜 형식 422 / 무토큰 401 | — | PASS | — |

- T66 검산 SQL(`verify_observations.sql`) 주간·월간 불일치 0행, 값은 T65 손 계산 정답과 같다.
- 대조 실험: 스냅샷 PYTHON 값을 0.7142로 바꾸면 API 검산·화면 검산 2건이 실패한다.
- 로컬 Backend + **Staging DB(읽기 전용 세션)**: `/health/db` 200, 무토큰·위조 토큰 `market-trends` 401. 인증 200 조회는 **승인된 테스트 계정이 없어 하지 않았다**(T16 선례: 인위적 토큰 발급 금지). 하더라도 0003 미적용으로 관측 조회 SQL이 실패한다.
- headless Chrome으로 1280px·375px 화면을 확인했다(가로 스크롤 없음, 콘솔 오류 0).

## 미검증 · 후속

- **Staging 실제 데이터 검산: BLOCKED** — 관측 0건, migration 0003 미적용, T66 미실행, T67 미배포. 순서: #171·#172·#174 병합 → 승인 절차로 0003 적용 → T66 실행(실수집은 T61 게이트) → 배포 → 승인된 테스트 계정으로 이 E2E 재실행
- 출처 선택 UI: 출처 목록 API가 없어 만들지 않았다. 관측 출처가 하나면 T67이 자동 선택하고, 둘 이상이면 422 문구로 안내한다. 출처가 늘면 목록 API(또는 응답 필드)와 함께 선택 UI를 추가한다
- 기준 시점: T67 응답에 집계 기준 시각(`as_of`)이 없어 "마지막 관측 구간"으로 표시한다. 계약에 필드가 생기면 바꾼다
- 스크린리더 실기기 확인은 하지 않았다(jsdom 접근성 이름·키보드 테스트만)
