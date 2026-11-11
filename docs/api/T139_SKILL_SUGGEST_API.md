# T139 — 기술 자동완성·동의어 검색 API (PROPOSED)

> 상태: **PROPOSED**. 서버 플래그 `SKILL_AUTOCOMPLETE_API` 는 기본 `false` 입니다. 꺼져 있으면 경로가 등록되지 않습니다(404).
> T17 `GET /api/v1/skills`(확정 계약)는 바꾸지 않았습니다. `docs/api/openapi.yaml` 에도 아직 넣지 않았습니다(PM 승인 후 반영).

## 1. 선행 일감과 현재 상태

| 선행 | 상태 | 이 PR 에서 쓰는 것 |
|---|---|---|
| T17 직무·기술 조회 API | main 병합(#117) | 공개 조회 방식(인증 선택), cursor 서명 키 파생(`derive_key`), `career.skills` |
| T98 고급 검색 계약 | main 병합(#201, PROPOSED) | 직접 의존 없음. 공고 검색 필터의 기술 코드 입력에 이 API 를 쓸 수 있음 |
| T137 코드·동의어 정책 | main 병합(#37). 리뷰 수정 #129 OPEN | §3 정규화·일치 순서·다의어 규칙을 Python 으로 옮김. **별칭 표는 migration 없음** |
| T138 코드 정제 Pipeline | **PR #154 OPEN (김예주)** | 직접 의존 없음. T138 이 비활성화한 코드(`is_active=false`)는 후보에서 빠짐 |

## 2. 계약

`GET /api/v1/skills/suggest?q=<검색어>&limit=<1..50, 기본 10>&cursor=<이전 next_cursor>`

- 인증: 필요 없음(T17 과 같음). `Authorization` 은 읽지 않습니다. 개인 데이터는 응답에 없습니다.
- 응답 200

```json
{
  "items": [
    {"code": "PYTHON", "name": "Python", "match_type": "alias", "matched": "파이썬", "skill_id": "…uuid…"}
  ],
  "next_cursor": null,
  "alias_source": "taxonomy"
}
```

| 필드 | 뜻 |
|---|---|
| `match_type` | `code`(코드 철자) → `alias`(exact 동의어, 병합된 옛 코드 철자 포함) → `ambiguous`(다의어 후보, 자동 선택 안 함) → `prefix`(앞부분) → `partial`(포함) 순으로 정렬 |
| `matched` | 실제로 일치한 표기(코드·이름·동의어) |
| `skill_id` | `career.skills` 에 있는 기술이면 id, 분류에만 있으면 `null`(등록 불가) |
| `alias_source` | `none` 이면 동의어 표 없이 이름·코드로만 찾은 결과 |

- 오류: 422 `VALIDATION_FAILED`(빈 값, 정규화 후 빈 값 `---`, 제어 문자, 60자 초과, limit 범위 밖), 400 `INVALID_CURSOR`(변조·다른 검색어·데이터 변경), 429 `RATE_LIMITED`(IP 당 60초 120회, PROPOSED), 503 `DEPENDENCY_UNAVAILABLE`(DB 오류 또는 출처 5000행 초과). 새 오류 코드는 만들지 않았습니다(T116 스냅샷 유지).

## 3. 규칙

1. **정규화**(T137 §3): 앞뒤 공백 제거 → NFKC → 소문자 → 공백·`.`·`-`·`_`·`/`·괄호 제거. `+`, `#` 은 남김(C++ ≠ C#). PostgreSQL `normalize_term()` 과 결과가 같음을 시험으로 확인했습니다.
2. **중복 제거**: 같은 표준 코드는 한 번만, 가장 좋은 일치만 남깁니다.
3. **병합·폐기**: merged 코드는 `replaced_by` 를 따라 살아 있는 코드로 바꿉니다(최대 5단계). 순환·초과 체인·deprecated 는 뺍니다.
4. **정렬**: 일치 종류 → 이름 길이 → 이름 → 코드. 같은 데이터면 항상 같은 순서입니다.
5. **페이지**: 정렬된 전체 결과를 offset 으로 자릅니다. cursor 는 HMAC-SHA256 서명이고 정규화된 검색어 해시와 분류 데이터 지문에 묶입니다. 데이터가 바뀌면 400 을 돌려 처음부터 다시 조회하게 합니다(중간 항목이 조용히 빠지지 않도록).

## 4. 데이터 출처와 한계

| 출처 | 쓰는 곳 | 동의어 |
|---|---|---|
| `career.skills` (code, name, is_active) | 기본 의존성(실제 DB, 읽기 전용 SELECT) | **없음**. T137 별칭 표가 migration 되지 않았기 때문 |
| `MemoryTaxonomySource` | 시험·Mock | 합성 동의어·병합·폐기 |

- 그래서 **실제 DB 에서 `파이썬` → `PYTHON` 변환은 아직 안 됩니다**(시험으로 빈 결과를 고정). 동의어 변환 PASS 는 합성 분류 기준입니다.
- 출처는 요청마다 활성 기술 전체(최대 5000행)를 읽고 서버 메모리에서 일치시킵니다. T10 Seed 규모(약 70행)에서는 충분합니다. 5000행을 넘으면 503 으로 거절합니다.

## 5. 인덱스 (제안과 실제 사용 구분)

- 제안: `database/proposed/T139_skill_suggest_index.sql` — `career.skills (code) WHERE is_active` 부분 인덱스. **적용하지 않았습니다.**
- 일회용 PostgreSQL 18.6 에서 확인한 실제 계획
  - 기본: `Seq Scan on skills` (행이 적어 인덱스를 쓰지 않음)
  - `enable_seqscan=off` 강제 시에만 `Bitmap Index Scan on ix_skills_t139_active_code`
- 결론: 현재 규모에서는 **인덱스 불필요**. 동의어 검색용 인덱스는 T137 `taxonomy_aliases(entity_type, alias_norm)` 표가 승인될 때 함께 정합니다.

## 6. 성능 (로컬 측정)

- 합성 5000개 항목(항목당 동의어 2개): 질의 1건 평균 약 34 ms (Windows 로컬, `T139_PERF` 출력). 시험 기준은 1초 미만.
- 실제 Seed(약 70행) HTTP 응답은 시험 안에서 즉시 반환. 부하 시험은 하지 않았습니다(NOT_RUN).

## 7. PM 결정 필요

1. 계약 승인 후 `openapi.yaml` 반영 여부와 경로 이름(`/skills/suggest`)
2. T137 별칭·상태 표 migration (T138 #154 의 결정 1번과 같음) — 승인되어야 실제 동의어 변환이 가능
3. 요청 한도(60초 120회)와 최소 입력 길이(정규화 후 1글자)
4. 직무 코드 자동완성(T137 직무 다의어 규칙 미확정) — 이번 범위는 기술만
