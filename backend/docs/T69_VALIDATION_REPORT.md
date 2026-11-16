# T69 채용시장 추세 예측 Baseline — 검증 보고서 (합성 데이터)

> 데이터 출처: `synthetic-t69-v1` (실제 시장 데이터 아님). 합성 데이터로 검증한 단순 기준선 예측이며, 확정된 시장 전망이나 채용 보장이 아닙니다.
> 생성: `python -m app.services.market_forecast_report` — 같은 코드면 같은 결과.

## 계절성+상승 추세 52주

- 지표 `posting_count` · 주기 `week` · 관측 52개 · 예측 기간 4 · 최소 학습 12 · fold 37
- 판정 **PASS** · 최선 후보 `seasonal_naive` · naive 대비 MAE 개선 60.5%
- 데이터 지문 `9efb60baa90180cb…`

| 모델 | MAE | WAPE | sMAPE |
|---|---:|---:|---:|
| naive | 22.514 | 13.5% | 13.9% |
| seasonal_naive | 8.892 | 5.3% | 5.6% |
| moving_average | 16.348 | 9.8% | 9.9% |
| drift | 22.841 | 13.7% | 14.0% |

## 빈 구간 3주 포함 52주

- 지표 `posting_count` · 주기 `week` · 관측 52개 · 예측 기간 4 · 최소 학습 12 · fold 37
- 판정 **PASS** · 최선 후보 `seasonal_naive` · naive 대비 MAE 개선 45.3%
- 데이터 지문 `e2d4152e758312c4…`

| 모델 | MAE | WAPE | sMAPE |
|---|---:|---:|---:|
| naive | 21.566 | 12.9% | 13.4% |
| seasonal_naive | 11.787 | 7.0% | 7.5% |
| moving_average | 16.507 | 9.9% | 10.1% |
| drift | 21.731 | 13.0% | 13.4% |

## 무작위 걸음 52주 (기준선 이기기 어려움)

- 지표 `posting_count` · 주기 `week` · 관측 52개 · 예측 기간 4 · 최소 학습 12 · fold 37
- 판정 **HOLD** · 최선 후보 `drift` · naive 대비 MAE 개선 -5.9%
- HOLD 사유: 최선 후보 drift가 naive 대비 MAE 5% 이상 개선하지 못함
- 데이터 지문 `bc30f6da7cc35dc9…`

| 모델 | MAE | WAPE | sMAPE |
|---|---:|---:|---:|
| naive | 8.230 | 9.1% | 8.9% |
| seasonal_naive | 9.946 | 11.1% | 10.9% |
| moving_average | 9.196 | 10.2% | 10.1% |
| drift | 8.713 | 9.7% | 9.4% |

## 데이터 부족 14주

- 지표 `posting_count` · 주기 `week` · 관측 14개 · 예측 기간 4 · 최소 학습 12 · fold 0
- 판정 **HOLD** · 최선 후보 `—` · naive 대비 MAE 개선 —
- HOLD 사유: 평가 fold 0개 < 최소 3개 (데이터 부족)
- 데이터 지문 `a17a82a74fd1df36…`

| 모델 | MAE | WAPE | sMAPE |
|---|---:|---:|---:|
| naive | — | — | — |
| seasonal_naive | — | — | — |
| moving_average | — | — | — |
| drift | — | — | — |

