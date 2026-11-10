# 적합도 규칙 `match_rule` v1 (T41)

> 요구사항 FR-ANL-001 · API `createMatch`(POST `/api/v1/matches`), `getMatch`(GET `/api/v1/matches/{match_id}`) · 테이블 `match_evaluations`
> 코드: [`app/services/match_rule.py`](../app/services/match_rule.py) (순수 함수), [`app/services/matching.py`](../app/services/matching.py) (업무 규칙)

점수는 **합격 확률이 아닙니다.** 응답의 `score_is_probability`는 항상 `false`입니다.

## 1. 계산 방법

| 단계 | 규칙 |
|---|---|
| 요구 기술 | 공고: `job_posting_skills` (필수/우대, `required_level`). 직무: `job_role_skills` (모두 필수) |
| 요구 수준 | 공고의 `required_level` → 없으면 공고 직무의 `job_role_skills.required_level` → 없으면 3 |
| 내 수준 | `user_skills.proficiency` (NULL은 0, 데이터 사전 B07 기준). 프로젝트 사용 기술(`user_project_skills`)은 최소 1 |
| 기술별 충족도 | `min(내 수준, 요구 수준) / 요구 수준` (0~1) |
| 가중치 | 필수 2, 우대 1 |
| 점수 | `100 × Σ(가중치 × 충족도) / Σ가중치`. 분수로 정확히 계산한 뒤 소수 둘째 자리에서 한 번만 반올림(half-up) |
| 충족 / 부족 기술 수 | 내 수준 ≥ 요구 수준이면 충족, 아니면 부족 |
| 요구 기술 없음 | 계산하지 않고 `status=failed`, `score=null` |

같은 입력이면 입력 순서와 관계없이 같은 점수가 나옵니다 (FR-ANL-001 수용 기준 1, `tests/test_match_rule.py`).

### 예시 (Golden Fixture)

| 요구 기술 | 내 수준 | 충족도 | 가중치 |
|---|---|---|---|
| A 필수 4 | 4 | 1 | 2 |
| B 필수 3 | 2 | 2/3 | 2 |
| C 필수 2 | 없음 | 0 | 2 |

점수 = 100 × (2 + 4/3 + 0) / 6 = 55.555… → **55.56**, 충족 1, 부족 2.
여기에 우대 D(요구 2)를 프로젝트에서만 썼다면 수준 1 → 충족도 1/2 → 100 × (10/3 + 1/2) / 7 = **54.76**.

## 2. 대상·권한 규칙

| 상황 | 결과 |
|---|---|
| `job_posting_id`와 `job_role_id`가 둘 다 있거나 둘 다 없음, 모르는 필드(`user_id` 등) | 422 `VALIDATION_FAILED` |
| 공고 없음, 초안(`draft`) 공고, 직무 없음, 비활성 직무 | 404 `NOT_FOUND` |
| 마감(`closed`) 또는 `expires_at`이 지난 공고 | 계산하고 한계 설명에 "마감된 공고입니다." 추가 |
| 보유 기술(`user_skills`) 0개 | 400 `NO_USER_SKILLS` (저장 안 함) |
| 승인된 `match_rule` v1이 `model_versions`에 없음 | 503 `DEPENDENCY_UNAVAILABLE` (저장 안 함) |
| 다른 사람의 결과 조회 | 404 `NOT_FOUND` |

## 3. 한계 설명 (`limitations`)

항상 첫 줄은 "자기평가 숙련도 기준이며 채용 결과를 예측하지 않습니다."이고, 해당할 때만 아래가 순서대로 붙습니다.
DB에는 줄바꿈으로 이어 `match_evaluations.limitations` 한 칸에 저장합니다.

1. 숙련도를 입력하지 않은 기술은 0으로 계산했습니다.
2. 프로젝트에서만 사용한 기술은 숙련도 1로 계산했습니다.
3. 마감된 공고입니다.
4. 요구 기술 정보가 없어 적합도를 계산할 수 없습니다. (`failed`일 때)

## 4. 계산 기준 등록 (운영 전 필요)

결과마다 `model_version_id`를 저장하므로(FR-ANL-001 수용 기준 3) `model_versions`에 **승인된** 행이 있어야 합니다.
T10 Seed는 `model_versions`를 넣지 않습니다(운영 기준 데이터는 T60 담당). 로컬·일회용 DB에서는 아래로 등록합니다.
**공유 Staging 적용은 T12/T60 승인 후에만** 합니다.

```sql
INSERT INTO career.model_versions (model_code, version, kind, description, approved_at)
VALUES ('match_rule', '1', 'rule',
        '보유 기술·숙련도와 요구 기술 비교 규칙 (backend/docs/MATCH_RULE.md). 합격 확률 아님', now())
ON CONFLICT (model_code, version) DO NOTHING;
```

## 5. 작업지시서와 다른 점·남은 일

| 항목 | 내용 |
|---|---|
| 경로 | 작업지시서는 `/api/v1/matches/evaluate`, T06 확정 계약은 `POST /matches`·`GET /matches/{match_id}` → **계약 기준**으로 구현 |
| 입력 스냅샷 | 작업지시서에 있으나 `match_evaluations`(T05/T09)에 저장할 컬럼이 없음. 같은 입력·같은 규칙 버전이면 같은 점수이므로 재계산으로 확인. 컬럼 추가는 T05/T09 담당과 협의 |
| 규칙 출처 | T27 Baseline(`app/services/recommendation_baseline.py`, `skill-overlap-draft-v2`)은 숙련도 없이 기술 겹침만 보는 **추천 순위용** 규칙(T45 추천 Run이 사용). 적합도는 숙련도·필수/우대 가중이 필요해 v1 규칙을 여기서 정의. 두 규칙을 하나로 합칠지는 T27 담당과 협의 후 버전을 올림 |
| 계산 기준 등록 | T45는 저장 시 `skill_overlap_baseline`을 승인 없이(approved_at NULL) 자동 등록하지만, 적합도는 **승인된** `match_rule` v1이 미리 있어야 계산(없으면 503). 등록은 위 SQL로 운영 담당이 수행 |
| 선행 일감 | T17·T18·T33 머지 후 같은 `table()` 선언을 재사용하도록 맞춤. 테스트는 메모리 저장소 + T05 DDL·T10 Seed PostgreSQL 통합 테스트 |
