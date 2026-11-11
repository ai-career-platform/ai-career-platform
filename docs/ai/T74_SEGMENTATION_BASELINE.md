# T74 사용자 군집 Baseline·품질 평가 (ML04 / F-025)

> 상태: **PARTIAL** — 합성 데이터 baseline·평가·테스트 PASS / 안정성 목표 미달(제안값 기준) / 임계값·실데이터 사용 PM 승인 전
> 작업지시서: [T74](../work-orders/remaining-30/T74.md) · 선행: T25(계약), T71(행동·동의 계약, DRAFT), T73(데이터 품질) · 모델 카드: [MODEL_CARD_T74_SEGMENTATION.md](MODEL_CARD_T74_SEGMENTATION.md)
> **이 baseline은 DB를 읽거나 쓰지 않으며 개별 배정 결과를 저장하지 않습니다. 합성(`synthetic_seed`) 데이터만 받습니다.**

## 1. 무엇을 만들었나

| 파일 | 내용 |
|---|---|
| `ml/segmentation/baseline.py` | 입력 검증 → 기술 숙련도 벡터 → k-means(k-means++, 결정적) → 평가 보고서. 표준 라이브러리만 사용 |
| `tests/t74/test_segmentation.py` | 단위·재현·안전 경계 테스트 15개 (DB·네트워크 불필요) |
| `.github/workflows/t74-segmentation.yml` | T74 전용 테스트만 Python 3.12에서 실행 |

기존 설계(T25 Feature 계약, T71 동의 계약, AI 시스템 구조 §3.1)를 그대로 따르며 새 테이블·Feature Store·외부 라이브러리를 만들지 않았습니다.

## 2. 데이터와 특징

- **입력:** T147 합성 공장의 AI 피처 JSONL (`entity_id`, `skills{코드:1~5}`, `dataset_version`, `source`). `source`가 `synthetic_seed`가 아니면 거부합니다. 승인된 실데이터 출처는 별도 승인 후 추가합니다.
- **특징 벡터:** 기술 숙련도/5. 미입력은 **계산 스냅샷에서만** 0으로 둡니다(원본을 덮어쓰지 않음, T25 §13).
- **사용하지 않는 것:** 성별·나이·건강·종교 등 민감·차별 우려 속성, 이름·이메일·IP 등 식별 정보(T71 §4). 이런 키가 행이나 `skills` 키에 있으면 **오류로 거부**합니다.
- **시점·동의 검사:** `consent=false`인 행과 `available_at`이 기준 시각(`--as-of`)보다 늦은 행은 **제외하고 사유별 건수만** 보고합니다(미래 데이터 누수 방지, 제외 행이 결과에 영향이 없음을 테스트로 확인).
- 중복 `entity_id`, 1~5가 아닌 숙련도, 서로 다른 `dataset_version` 혼합, 시간대 없는 시각도 거부합니다.

## 3. 평가 지표

| 지표 | 정의 | 제안 목표(미승인) |
|---|---|---|
| Silhouette | 평균 silhouette(유클리드) | ≥ 0.10 |
| Seed 안정성 | seed 5개로 군집화한 결과의 쌍별 ARI 평균 | ≥ 0.80 |
| 최소 군집 크기 | 5명 미만 군집이 없을 것 (T71 k=5) | ≥ 5 |
| 표현 비율(편향) | (군집 내 집단 비중)/(전체 집단 비중), 5명 이상 군집만 | 0.5 ~ 2.0 |
| 활용성 참고 | 군집과 사용자가 밝힌 목표 직무의 ARI (참고용) | 목표 없음 |

- 집단 라벨(편향 평가)과 기준 라벨(활용성)은 **평가에만** 쓰이고 군집 입력이 아닙니다. 라벨 유무로 군집 결과가 달라지지 않음을 테스트로 확인합니다.
- 임계값은 **제안**입니다. PM 승인 전에는 PASS 판정 기준으로 쓰지 않고 `target_check`로만 보고합니다.
- 보고서에는 `entity_id`·개별 배정이 없고, 5명 미만 군집의 크기는 `<5`로 가립니다.

## 4. 실행 방법

```bash
python -B database/fixtures/synth_factory.py --target-env local --seed 74 --users 300 --companies 10 --postings 20 \
  --out-sql /tmp/synth.sql --out-features /tmp/features.jsonl
python -B -m ml.segmentation.baseline --input /tmp/features.jsonl --as-of 2026-11-11T00:00:00+00:00 \
  --k-max 16 --seed 74 --out /tmp/t74_report.json
python -B -m unittest discover -s tests/t74 -v
```

같은 입력·`--seed`면 보고서(`report_fingerprint` 포함)가 완전히 같습니다. 300명·k 2~16 평가는 약 30초 걸립니다(순수 Python O(n²) silhouette).

## 5. 결과 (합성 300명, seed 74, `t147.2:seed74`)

| 항목 | 값 |
|---|---|
| 선택된 k | 14 (k 8~16에서 silhouette 0.17~0.18로 거의 평평) |
| Silhouette | 0.1819 (제안 목표 ≥ 0.10 충족) |
| Seed 안정성 ARI | 평균 0.553 / 최소 0.468 (**제안 목표 0.80 미달**) |
| 최소 군집 크기 | 8 (충족) |
| 군집-목표직무 ARI | 0.509 (합성 직무 12종) |
| 특징 분포 | 사용자당 기술 3개 고정, 28종 |

**해석**
- 합성 데이터는 사용자당 기술이 3개뿐인 희소 벡터라 군집 경계가 뚜렷하지 않고 k가 커질수록 silhouette이 완만하게만 오릅니다. 군집이 목표 직무와 어느 정도(ARI 0.51) 맞아 활용 가능성은 보이지만, **seed에 따라 군집이 꽤 달라집니다(안정성 미달).**
- 임계값을 결과에 맞춰 낮추지 않았습니다. 실제 특징(기술 수·행동 집계)이 확정되면 같은 도구로 재평가해야 합니다.
- 테스트의 명확한 합성 군집(겹치지 않는 기술 묶음)에서는 ARI 1.0, 안정성 목표 충족을 확인해 도구 자체의 정확성은 검증했습니다.

## 6. 안전·권한 경계

- DB·네트워크 접근 없음, 파일 저장은 `--out`으로 지정한 보고서 하나뿐입니다. 공유 Staging·운영 설정은 건드리지 않습니다.
- `ai_career_poc` SUPERUSER 사용 없음. 이 도구는 DB 접속 정보를 받지 않습니다.
- 개별 사용자에게 세그먼트를 노출하거나 불이익에 쓰는 기능은 없습니다(별도 정책 승인 대상, T75).

## 7. 미해결·후속 (PM·담당자 결정 필요)

1. 평가 임계값 4종 승인 (특히 seed 안정성 0.80 적정성)
2. 군집 입력 특징 확정: 기술 숙련도만으로 충분한지, 동의된 행동 집계(T71 이벤트)를 쓸지 — 행동 이벤트는 정책 미승인(T71 DRAFT)이라 사용하지 않았습니다.
3. 실데이터 사용 승인과 `ALLOWED_SOURCES` 확장, 동의 철회·삭제의 파생 데이터·모델 전파(T25 P0 OPEN)
4. 결과 저장(`user_segments/assignments`)은 T05/T09 확정 전이라 만들지 않았습니다. T75는 이 보고서의 집계 필드(`cluster`, 크기, `segmentation_version`)를 mock으로 사용할 수 있고, 사람이 읽는 `label` 규칙은 정해야 합니다.
5. 대규모 데이터(수천 명 이상)에서는 순수 Python silhouette이 느려 NumPy·scikit-learn 도입 여부를 결정해야 합니다.
6. CI: 이 PR의 T74 워크플로 실행 결과는 PR 생성 후 확인합니다. 실행 전에는 CI PASS로 보고하지 않습니다.
