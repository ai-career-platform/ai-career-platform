# T65 — 채용시장 지표·관측 데이터 계약

> 상태: **PROPOSED (PR 리뷰 대상)** · 작성: 2026-11-09 · 담당: 채희주 (kixxuya) · Redmine [#1597](https://sulfite-footbath-next.ngrok-free.dev/issues/1597)
> 기능: F-024 / FR-ANL-005 / UI-024 · 적용: T66 집계 Pipeline, T67 조회 API, T68 대시보드, T69 예측 Baseline
> 근거: [T65 작업지시서](../work-orders/remaining-30/T65.md), [데이터 사전 F05·F06](../../database/DATA_DICTIONARY.md), [OpenAPI `/market-trends`](../api/openapi.yaml), [출처 레지스트리](SOURCE_REGISTRY.md)

## 0. 이번 계약에서 결정된 것

| 항목 | 결정 | 근거 |
|---|---|---|
| 지표 | `posting_count`, `skill_demand_share` 2개 | OpenAPI `metric_code` enum, FR-ANL-005 "공고 수, 기술 수요 비율" |
| 기술 차원 저장 | `market_observations`·`market_forecasts`에 `skill_id` 추가 ([migration 0003](../../database/migrations/0003_market_metric_skill_dimension.sql)) | PM/JM 조정민 2026-11-09 Slack: "DB 명세 migration으로 바꿔도 되니 최선인 걸로" |
| 전체 시장 행 중복 | `job_role_id IS NULL` 행의 UNIQUE 중복 허용(NULLS DISTINCT)은 **바꾸지 않는다**. 적재 쪽이 막는다 (§5) | 같은 날 PM/JM 결정 "대응하지 말고 그대로" |

## 1. 지표 카탈로그

| metric_code | 의미 | 단위 | 값 | 차원 | 최소 표본 |
|---|---|---|---|---|---|
| `posting_count` | 구간 안에 **새로 게시된** 공고 수 | 건 (`count`) | 0 이상 정수 | 출처 × 직무(또는 전체) × 구간 | 없음 (0도 값) |
| `skill_demand_share` | 구간 안 신규 공고 중 그 기술을 요구한 공고 비율 | 비율 (`ratio`, 0~1) | 소수 넷째 자리 반올림 | 출처 × 직무(또는 전체) × **기술** × 구간 | 같은 범위의 `posting_count` **5건 이상** |

- 단위는 DB에 컬럼으로 두지 않고 이 표가 기준이다. T67 응답의 단위 표기도 이 표를 따른다.
- 화면 표시(T68): `skill_demand_share`는 퍼센트(×100)로 보여줄 수 있으나 저장·API 값은 0~1이다.
- DB가 값 범위를 막는다: `posting_count`는 0 이상 정수, `skill_demand_share`는 0~1, `skill_id`는 `skill_demand_share`에만 있다 (migration 0003 CHECK).
- 새 지표를 추가할 때는 이 표와 OpenAPI enum, 필요하면 CHECK를 함께 바꾼다.

## 2. 왜 "신규 게시 수"인가

FR-ANL-005의 사용자 질문은 "관심 직무의 공고가 **늘고 있는지**"다. 구간별 신규 게시 수는

- 게시 시각(`published_at`)만으로 정해져 마감일 정보가 없거나 부정확해도 흔들리지 않고 ([T63 lifecycle](../../crawler/quality/README.md): `expires_on` 없으면 만료를 추정하지 않음),
- 한 번 정해진 구간 값이 나중 데이터에 덜 흔들려 예측(T69)의 학습 대상으로 쓰기 쉽다.

"특정 시점에 열려 있는 공고 수(재고)"는 마감·삭제 판정이 안정된 뒤 별도 지표로 추가한다 (§10).

## 3. 계산 규칙

검산 SQL: [`database/market_metrics/reference_metrics.sql`](../../database/market_metrics/reference_metrics.sql). T66은 이 결과와 **차이 0**이어야 한다.

### 3.1 집계 대상 공고

`career.job_postings`에서 모두 만족하는 행:

1. `source_id` = 집계 출처
2. `status IN ('published', 'closed')` — 마감된 공고도 게시된 적이 있으므로 포함, `draft` 제외
3. `published_at IS NOT NULL` 그리고 `published_at <= as_of`
4. `created_at <= as_of` — 플랫폼이 그 공고를 **알게 된 시각**이 기준 시각 이전 (§4)

`skill_demand_share`의 기술은 `career.job_posting_skills`에서 `created_at <= as_of`인 것만 쓴다. `is_required`는 구분하지 않는다(우대 기술도 수요로 본다).

### 3.2 시간대와 구간

- 모든 날짜 계산은 **Asia/Seoul(KST)**. `published_at`을 KST 날짜로 바꾼 뒤 구간에 넣는다.
- `period`: `week`(기본, 월~일), `month`(1일~말일), `day`.
- `observed_on` = **구간 시작일** (주=월요일, 월=1일, 일=그날).
- **완료된 구간만** 값을 낸다: 구간 끝(다음 구간 시작일)이 `as_of`의 KST 날짜 이하일 때. 진행 중인 이번 주·이번 달은 저장하지 않는다.

### 3.3 직무 범위

- `job_role_id IS NULL` 행 = **전체 시장**. 직무가 없는 공고도 포함한다.
- 직무별 행은 `as_of`까지 그 출처에 공고가 **한 건이라도 있었던 직무**만 만든다(조회 구간과 무관). 그런 직무는 관측된 구간에서 0건이면 `0` 행을 둔다(빈 구간과 구분하기 위해). 조회 구간에 따라 직무 목록이 바뀌지 않아야 일부 구간만 다시 계산해도(T66) 전체 재계산과 결과가 같다.
- 직무가 없는 공고는 직무별 행에 넣지 않는다.

### 3.4 빈 구간과 0

| 상황 | 저장 | 화면 (FR-ANL-005 수용 기준 3) |
|---|---|---|
| 구간에 공고가 있음 | 값 | 값 |
| 공고는 없지만 그 구간 안에 **성공한** 수집 실행(`ingestion_runs.status='succeeded'`, `ended_at` KST 날짜 기준)이 있음 | `0` | 0 |
| 공고도 없고 성공한 수집도 없음 (실패만 있거나 기록 없음) | **행 없음** | 빈 구간 ("데이터 없음") |

`skill_demand_share`는 그 구간에 한 번이라도 등장한 기술만 행을 만든다. 같은 범위의 `posting_count`가 5건 이상인데 기술 행이 없으면 그 기술 비율은 0이다. 5건 미만이면 비율 행을 만들지 않는다.

### 3.5 출처

- 값은 **출처별로** 계산·저장한다. 여러 출처를 더하지 않는다. 출처 간 같은 공고를 묶는 규칙이 아직 없기 때문이다.
- 1차 운영 출처는 잡코리아 단일 출처다 ([SOURCE_REGISTRY](SOURCE_REGISTRY.md)). 실수집은 T61 게이트에 따라 HOLD이므로 현재 검증은 합성 fixture로만 한다.
- 화면에는 출처 이름과 "잡코리아 게시 공고 기준 표본" 문구를 함께 표시하고, **시장 전체 수요로 확대 해석하지 않는다** (작업지시서 §5).

### 3.6 반올림

`skill_demand_share = round(기술 공고 수 / 신규 공고 수, 4)`. PostgreSQL `numeric` 반올림(0.5는 0에서 먼 쪽)이다.

## 4. 시점 누수와 늦게 들어온 데이터

- 모든 계산은 기준 시각 `as_of`를 받는다. `as_of` 이후에 저장된 공고·기술 정보는 쓰지 않는다. 같은 DB와 같은 `as_of`면 언제 다시 돌려도 같은 결과다.
- 크롤링은 게시 후 며칠 뒤에 공고를 가져올 수 있다. 그래서 **T66은 매 실행마다 최근 2개 구간을 다시 계산해 덮어쓰고, 그보다 오래된 구간은 고정**한다.
- 늦게 들어온 공고는 **자기 게시 구간만** 바꾼다. 다른 구간 값은 그대로다 (fixture E7로 검증).
- T69 예측 학습은 "학습 기준 시각까지 알 수 있던 값"만 쓴다. 고정 구간 값은 그 조건을 만족한다. 최근 2개 구간은 학습에서 빼거나 재계산 가능성을 감안한다.

## 5. 저장 (`career.market_observations`)

| 컬럼 | 값 |
|---|---|
| `source_id` | 집계 출처 |
| `job_role_id` | 직무, 전체 시장이면 NULL |
| `skill_id` | `skill_demand_share`일 때 기술, 그 외 NULL (CHECK로 강제) |
| `observed_on` / `period` | §3.2 |
| `metric_code` / `metric_value` | §1 |

고유 키 (migration 0003):

- 기술 없는 지표: `(source_id, job_role_id, metric_code, period, observed_on) WHERE skill_id IS NULL` — 0001과 같은 키·동작
- 기술별 지표: `(source_id, job_role_id, skill_id, metric_code, period, observed_on) WHERE skill_id IS NOT NULL`

**PostgreSQL은 UNIQUE에서 NULL끼리 다르다고 본다.** 그래서 전체 시장(`job_role_id IS NULL`) 행은 DB가 중복을 막지 못한다. PM 결정에 따라 인덱스는 그대로 두고, **T66은 다시 계산하는 구간의 기존 행을 (출처, 기간 종류, 구간 범위) 단위로 지운 뒤 한 트랜잭션에서 다시 넣는다.** `ON CONFLICT`에 기대지 않는다. 이 동작은 `test_null_role_duplicates_are_left_as_is`로 고정돼 있다.

## 6. 경계 사례와 검증 fixture

fixture: [`t65_fixture.sql`](../../database/market_metrics/t65_fixture.sql) (출처 `t65_fixture`) · 정답: [`t65_expected.json`](../../database/market_metrics/t65_expected.json)

| ID | 사례 | fixture | 기대 |
|---|---|---|---|
| E1 | 직무 없는 공고 | p6, p7 | 전체 시장에만 포함 |
| E2 | KST 주 경계 | p6 `10-11 23:30 KST` / p7 `10-12 00:10 KST`(UTC로는 10-11) | p6은 1주차, p7은 2주차 |
| E3 | 마감 공고 | c1 `closed` | 게시 구간에 포함 |
| E4 | 작성 중 공고 | d1 `draft` (기술 PYTHON 있음) | 공고 수·기술 비율 모두 제외 |
| E5 | 표본 부족 | 1주차 프론트엔드 1건 | `posting_count`=1, 기술 비율 행 없음 |
| E6 | 공고 0건 + 수집 성공 | 3주차 성공 실행 | 전체·직무 모두 `0` |
| E7 | 늦게 수집된 공고 | p9 게시 10-27, 저장 11-03 | `as_of`=11-02이면 4주차 없음, 11-10이면 4주차만 생기고 1~3주차 불변 |
| E8 | 기준 시각 이후 게시·진행 중 구간 | p11 게시 11-05, 5주차 | `as_of`=11-02에서는 제외 |
| E9 | 수집 실패만 있는 구간 | 4주차 `failed` 실행 | 행 없음(빈 구간) |
| E10 | 다른 출처 혼합 | Seed `synthetic_seed` 공고 100건 | `t65_fixture` 결과에 섞이지 않음 |

손 계산 예 (1주차, `as_of`=2026-11-02 09:00 KST): 대상 7건(p1~p6, c1).
PYTHON 5건 → 5/7 = **0.7143**, JAVA 2건 → **0.2857**, TYPESCRIPT 1건 → **0.1429**.
백엔드 5건 중 PYTHON 4건 → **0.8000**, JAVA 2건 → **0.4000**.

## 7. 예측값 (`career.market_forecasts`, T69·T67)

- 예측은 관측과 **다른 테이블**에 두고, API·화면에서도 섞지 않는다 (FR-ANL-005 수용 기준 1).
- `metric_code`·단위·`skill_id` 규칙은 관측과 같다. `forecast_for`는 예측 대상 구간의 시작일이다.
- 예측 행은 반드시 `model_version_id`가 있다. 범위(`lower_bound`/`upper_bound`)가 있으면 함께 보여준다.

## 8. 조회 API에 넘기는 규칙 (T67)

- 필터: `metric_code`(필수), `from`·`to`(필수), `job_role_id`(없으면 전체 시장), `skill_id`(`skill_demand_share`면 필수), `period`(기본 `week`).
- 응답에 `source`(출처 코드·이름), `period`, 단위, 관측/예측을 분리해 담는다 (OpenAPI `MarketTrend`).
- 행이 없는 구간은 응답에서 빼거나 `null`로 둔다. **0으로 채우지 않는다** (§3.4).
- `skill_id` 쿼리 파라미터는 OpenAPI에 아직 없다. T67에서 추가한다.

## 9. 검증 방법과 결과

```powershell
# 일회용 PostgreSQL 18.1 (career 스키마를 지우고 다시 만든다. 공용·Staging DB 금지)
docker run -d --name t65-pg -e POSTGRES_PASSWORD=<임의값> -p 127.0.0.1:55433:5432 postgres:18.1
cd backend
$env:T15_TEST_DATABASE_URL = "postgresql://postgres:<임의값>@127.0.0.1:55433/postgres"
.\.venv\Scripts\python.exe -m pytest -q tests/test_t65_market_metrics_postgres.py
```

| 검사 | 결과 (2026-11-09, PostgreSQL 18.1) |
|---|---|
| S1 주간·p9 수집 전 / S2 주간·p9 수집 후 / S3 월간: 검산 SQL = 손 계산 정답 | PASS |
| 같은 입력 재실행 결과 동일 | PASS |
| 늦게 수집된 공고가 자기 구간만 변경 | PASS |
| 다른 출처 혼합 없음 | PASS |
| migration 0003 제약: 기술별 다중 행 허용, 중복·차원 짝·값 범위 위반 거부 | PASS |
| 전체 시장 행 NULL 중복은 DB가 막지 않음 (PM 결정 고정) | PASS (의도된 동작) |
| `database/migrate.py apply` 0001→0003 신규 DB 적용·`verify` | PASS |
| `check_data_dictionary.py` 사전 검증·T05 스냅샷·ERD 재생성 | PASS |

CI에서는 `Backend tests` 워크플로의 PostgreSQL 서비스로 같은 테스트가 돈다.

## 10. 제한사항과 후속

- **재게시 공고:** 같은 공고가 새 ID로 다시 올라오면 별도 공고로 센다. 같은 공고를 묶는 기준은 T63 후속에서 정한다.
- **직무·기술 매핑 품질:** 공고의 `job_role_id`·`job_posting_skills`가 비어 있거나 틀리면 지표도 그만큼 틀린다. 매핑은 T62/T63·T138 범위다.
- **재고(열린 공고 수) 지표:** 마감·삭제 판정이 안정되면 `open_posting_count` 등을 추가 검토한다.
- **보존:** 관측값은 출처 `data_sources.retention_days`를 따른다(데이터 사전 F05). 원문이 지워져도 집계값을 남길 수 있는지는 출처 권리 확인 사항이다 (SOURCE_REGISTRY W24-03 유형 질문).
- **Staging 적용:** migration 0003의 Staging 적용은 `database/migrations/README.md` §5 절차(백업 확인, 지정 실행자)로 별도 진행한다. 이 PR은 Staging DB를 바꾸지 않는다.
