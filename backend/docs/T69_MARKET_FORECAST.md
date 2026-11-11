# T69 채용시장 추세 예측 Baseline — 구현 기록

Redmine #1561 · 작업지시서 `docs/work-orders/remaining-30/T69.md` · F-024 / FR-ANL-005 / ML05 · 브랜치 `task/t69-market-forecast-baseline`
상태 **PARTIAL** — 선행 T65(지표 계약)·T66(집계 Pipeline) 미완료로 **합성 데이터 기준**만 검증. DB·API 연동 없음.

## 무엇을 만들었나

| 파일 | 역할 |
|---|---|
| `app/services/market_forecast.py` | 순수 계산 모듈. 입력 검증, 기준 모델 4종, 예측 범위, 지표, rolling 백테스트, PASS/HOLD 판정, 모델 버전·데이터 지문, `market_forecasts` 행 변환 |
| `app/services/market_forecast_synthetic.py` | seed 고정 합성 시계열(주간 공고 수). 계절+추세, 빈 구간, 무작위 걸음 |
| `app/services/market_forecast_report.py` | 검증 보고서 생성기 → `docs/T69_VALIDATION_REPORT.md` |
| `tests/test_market_forecast.py` | 42개 테스트 |

### 기준 모델 (모두 `kind=rule`, 외부 호출 없음)

| 모델 | 예측 방법 |
|---|---|
| `naive` | 직전 값 그대로 — **비교 기준선** |
| `seasonal_naive` | 한 주기(기본 4주) 전 값 반복 |
| `moving_average` | 최근 k개(기본 4) 평균 |
| `drift` | 첫 값~마지막 값 기울기로 연장 (0 미만은 0) |

예측 범위(`lower_bound`/`upper_bound`): 학습 구간 안 1-step 잔차의 RMS × 1.2816 × √h (약 80% 근사, 하한 0). 표시용 범위이며 보장값이 아니다.

### 검증 방법

- **rolling-origin 백테스트**: 기준 시점마다 그 시점 **이하** 관측만으로 학습(`history_as_of`) → 다음 h(기본 4)개 예측 → 실제와 비교. 최소 학습 12개.
- **지표**: MAE, WAPE(Σ|오차|/Σ|실제|, 실제 합 0이면 정의 불가 → None), sMAPE(둘 다 0인 항은 0). 아키텍처 문서(MAE/sMAPE)와 작업지시서(MAE/WAPE)를 모두 충족.
- **판정**: fold < 3이면 HOLD(데이터 부족). naive를 제외한 최선 후보가 naive보다 **MAE 5% 이상** 낫지 않으면 HOLD. 그 외 PASS. 임계값은 설정값으로 보고서에 기록.
- **빈 구간**: `value=None`으로 표현하고 평가에서 제외(0으로 채우지 않음) — FR-ANL-005 수용 기준 3.

### 누수 방지 (T25 `event_time ≤ decision_time` 원칙)

- `forecast(history, as_of, …)`는 `as_of` 이후 날짜가 학습 입력에 있으면 `LeakageError`.
- 백테스트는 fold마다 학습 마지막 날짜 < 평가 첫 날짜를 확인.
- 테스트: 판단 시점 이후 값을 99999로 바꿔도 그 시점 예측이 **완전히 같음**을 4개 모델 모두 확인.

### 재현성·모델 버전

- `model_version`: `model_code=market_trend_baseline`, `version=t69-baseline-1`, `kind=rule`, `selected_model`(PASS일 때만), 설정값, **입력 데이터 sha256 지문**.
- 같은 입력 → 같은 결과(테스트). 커밋된 보고서가 현재 코드 결과와 다르면 테스트 실패.

## 검증 결과 (합성 데이터) — 상세는 `docs/T69_VALIDATION_REPORT.md`

| 데이터 | fold | 판정 | 최선 | naive 대비 MAE |
|---|---:|---|---|---:|
| 계절성+상승 추세 52주 | 37 | PASS | seasonal_naive | 60.5% 개선 |
| 빈 구간 3주 포함 52주 | 37 | PASS | seasonal_naive | 45.3% 개선 |
| 무작위 걸음 52주 | 37 | **HOLD** | drift | -5.9% (기준선 못 이김) |
| 데이터 부족 14주 | 0 | **HOLD** | — | — |

→ "기준선 대비 평가·재현성과 미달 시 HOLD 판정 가능"(T69 DoD) 충족을 합성 데이터로 확인.

## 하지 않은 것 (후속)

| 항목 | 이유·담당 |
|---|---|
| 실제 시장 관측 데이터 | T65 지표 계약·T66 집계 Pipeline 미완료 → 합성 데이터만 |
| DB 저장(`market_forecasts`)·`model_versions` 등록 | `to_forecast_rows`로 행 모양만 제공. 저장은 T66/T67 연동 시 |
| 조회 API `GET /api/v1/market-trends` | T67 범위 |
| 월 단위 계절 주기 자동 설정 | 현재 `season` 인자로 지정 (주간 기본 4) |
| 권한·보안 경계 | 순수 계산 모듈이라 사용자 입력·인증 경로 없음. API(T67)에서 검증 필요 |

## 재현

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_market_forecast.py
.\.venv\Scripts\python.exe -m app.services.market_forecast_report   # 보고서 출력
```

공용 Staging DB 접속·변경 없음. Schema/Migration/Seed 변경 없음. 비밀정보·실사용자 데이터 없음.
