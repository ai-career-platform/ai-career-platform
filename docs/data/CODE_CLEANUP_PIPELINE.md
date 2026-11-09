# 스킬·직무 코드 정제·변경 이력 Pipeline (T138)

> 상태: **DRAFT / NOT APPROVED / NOT MIGRATED** · 2026-11-09
> 근거: [작업지시서 T138](../work-orders/fifth-30/T138.md), [T137 코드·동의어 정책](CODE_TAXONOMY_POLICY.md) §3·§5, 0001 스키마(T09), T10 Seed
> 선행 일감: **T10 완료**(#34), **T137 완료**(#37, PARTIAL). 정책 §9-4 "상태·별칭·이력 표를 실제 테이블에 넣을지"가 미확정이라 **마이그레이션 없이 mock 으로 검증**합니다.

## 1. 무엇을 하나

T137 이 "코드를 어떻게 합치고 폐기하는지" 규칙을 정했다면, T138 은 그 결정을 **이미 저장된 데이터에 반영**합니다.

| 단계 | 하는 일 |
|---|---|
| 1. 사전 점검 `preflight` | 순환·5단계 초과 체인, T137 `validate_taxonomy()` 위반, career 에 없거나 비활성인 병합 대상을 찾으면 **아무것도 바꾸지 않고 중단** |
| 2. 상태 반영 | 분류체계에서 `deprecated`·`merged` 인 코드 → `career.skills/job_roles.is_active = false` (행은 삭제하지 않음) |
| 3. 참조 이전 | 병합된 옛 코드를 가리키는 **현재 상태 표**의 행을 살아 있는 코드로 옮김 |
| 4. 이력 | 바꾸거나 정리한 행은 바꾸기 **전 원본**을 `remap_log` 에 남김 (수정·삭제 불가) |
| 원본 용어 정제 `stage_terms` | 공고·입력의 기술 표기를 코드로 변환. 다의어·미등록은 `term_review_queue` 로 (자동 선택 안 함, 정책 §3) |

## 2. 구성 (혼합 방식)

| 위치 | 내용 |
|---|---|
| `career` (0001 + T10 Seed) | **실제 구조 그대로** 이전 대상. 테이블 변경 없음 |
| `taxonomy_mock` (T137 mock) | 코드·별칭·상태·변경 이력 (그대로 사용) |
| `taxonomy_pipeline_mock` (T138 mock) | `pipeline_runs`, `remap_log`, `term_review_queue`, 함수 |

파일: [`database/tests/taxonomy/T138_code_cleanup_pipeline_mock.sql`](../../database/tests/taxonomy/T138_code_cleanup_pipeline_mock.sql), [`database/tests/test_code_cleanup_pipeline.sh`](../../database/tests/test_code_cleanup_pipeline.sh)

## 3. 이전 대상과 중복 규칙

같은 대상이 옛 코드와 새 코드를 **둘 다** 가지면 PK 가 겹치므로 아래처럼 합치고 옛 행은 정리합니다 (2026-11-09 결정: 높은 값 유지).

| 표 | 중복 시 |
|---|---|
| `user_skills` | `proficiency` 높은 쪽 |
| `job_posting_skills` | `is_required` 는 하나라도 필수면 필수, `required_level` 높은 쪽 |
| `job_role_skills` | `required_level` 높은 쪽 |
| `user_project_skills` | 비교할 값 없음 → 옛 행만 정리 |
| `user_target_roles` | 더 높은 순위 (`priority` 1 = 1순위, 즉 **작은 숫자**) |
| `job_postings.job_role_id` | 공고당 1개라 중복 없음 |

**옮기지 않는 표** (2026-11-09 결정): `skill_gap_items`, `skill_gap_assessments`, `match_evaluations`, `market_observations`, `market_forecasts` — 당시 모델·코드로 만든 결과 기록이라 그대로 둡니다. 옛 코드 행이 남아 있어 FK 와 조회는 계속 동작합니다.

## 4. 실행

```sql
SET ROLE t138_operator;
SELECT * FROM taxonomy_pipeline_mock.preflight('skill');               -- block/warn 목록
SELECT * FROM taxonomy_pipeline_mock.run_cleanup('skill', 'dry_run');  -- 건수만, 아무것도 안 바뀜
SELECT * FROM taxonomy_pipeline_mock.run_cleanup('skill', 'apply');    -- 반영
SELECT * FROM taxonomy_pipeline_mock.stage_terms('skill', 'posting:jobkorea', ARRAY['파이썬', 'Spring']);
```

- `dry_run` 은 같은 작업을 savepoint 안에서 하고 되돌려서 **정확한 예상 건수**만 `pipeline_runs.summary` 에 남깁니다.
- 같은 종류(`skill`/`job_role`)는 advisory lock 으로 한 번에 하나만 실행됩니다.
- 다시 실행하면 바꿀 행이 없어 0건입니다 (멱등).

## 5. 검증 (일회용 DB 전용)

```bash
D1_TEST_ONLY=YES bash database/tests/test_code_cleanup_pipeline.sh
```

| 구분 | 확인 항목 |
|---|---|
| 사전 점검 | 순환(트리거 우회), 정리 안 된 체인 A→B→C, career 에 없는 대상, 비활성 대상 → `blocked` + 데이터 변화 없음 |
| dry run | 예상 건수 보고, 데이터·로그 변화 없음, apply 결과와 건수 일치 |
| 중복 규칙 | 숙련도 2+4→4, 5+1→5, 공고 필수/수준, 직무 수준, 프로젝트, 목표 직무 순위 |
| FK·원본 보존 | 옛 코드 참조 0건, 옛 코드 행 유지(`is_active=false`), 원본·유지 행이 `remap_log` 에 남음, 변경 1건당 로그 1건 |
| 멱등성 | 두 번째 apply 0건, 데이터 지문(md5) 동일 |
| 용어 정제 | 한글 별칭·짧은 별칭·병합 코드 추적, 다의어 후보 2개 보존, 미등록 대기, 재등록 시 중복 없음 |
| 거부·권한 | 잘못된 mode·종류·source, app/reader/T137 역할 실행 거부, 내부 함수 직접 호출 거부, `remap_log` 수정·삭제 거부, career 직접 수정 거부 |

로컬 PostgreSQL 16 결과: **49 PASS** (`T138_CODE_CLEANUP_TEST=PASS`). 규칙을 일부러 틀리게 바꾸면(높은 값→낮은 값) 테스트가 실패하는 것도 확인했습니다. 리뷰 중인 #129 의 T137 mock 으로 바꿔 실행해도 PASS 입니다. 기존 CI 워크플로는 수정하지 않았습니다(T137 과 같은 방식).

## 6. 미확정 항목 (PM·담당자 결정 필요)

1. 정책 §9-4: `status`·`replaced_by`·별칭·이력 표를 실제 테이블에 넣을지. 넣으면 이 mock 을 마이그레이션으로 옮깁니다 (함수는 스키마 이름만 바뀜).
2. 정책 §9-5: 배치 실행 주기 (병합 직후 수동 / 정기).
3. 정책은 병합 체인을 5단계까지 허용하지만 T137 `validate_taxonomy()` 는 "병합 대상이 active 가 아님"을 위반으로 봅니다. 지금은 안전하게 **체인이 남아 있으면 중단**하고 큐레이터가 A 를 C 로 다시 가리키게 합니다.
4. `term_review_queue` 를 누가 처리하는지, 처리 결과를 별칭 등록(`add_alias`)으로 이어갈지.
5. 실제 반영 전 백업·복원 확인(T114)과 Staging 실행자.

**판정:** `T138_STATUS=PARTIAL` — 실제 0001 구조·T10 Seed 위에서 이전 로직 PASS, 분류체계 표는 mock (정책 §9-4 결정 전), Staging 미적용.
