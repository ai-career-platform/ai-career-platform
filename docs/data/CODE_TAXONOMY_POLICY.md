# 스킬·직무 표준 코드·동의어 관리 정책 (T137)

> 상태: **DRAFT / NOT APPROVED / NOT MIGRATED** · 2026-11-06 (T05 완료 후 개정)
> 근거: [작업지시서 T137](../work-orders/fifth-30/T137.md), B04 `job_roles`·B05 `skills` ([T05 데이터 사전 v0.2](../../database/DATA_DICTIONARY.md)), [API 계약](../API_CONTRACT.md) "식별자: `code`는 안정적인 직무·기술 식별", T10 초기 Seed(직무 30·기술 100 코드, PR #15 리뷰 중)
> 선행 일감: **T05 완료**(PR #17). T10(초기 Seed)은 같은 담당자가 함께 진행 중이고 T17(직무·기술 조회 API)은 진행 중이라, 이 문서는 **정책과 일회용 DB mock 검증까지만** 다룹니다. 실제 테이블 변경·자동완성 API(T139)·정규화 파이프라인(T138)은 **HOLD** 입니다.

## 0. T05 데이터 사전과의 관계

| T05 (B04 `job_roles`, B05 `skills`) | 이 정책 |
|---|---|
| `code varchar(64) UQ`, `CHECK (length(btrim(code)) > 0)` | 형식을 `^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$` 로 좁히는 CHECK 추가 제안 |
| `is_active boolean` — 폐기 시 `false` (참조 보존, 삭제 안 함) | 그대로 따름. `active` 상태 = `is_active true`, `deprecated`·`merged` = `false` (mock 에서 생성 컬럼으로 연결) |
| 대체 코드·별칭·변경 이력 없음 | `status`, `replaced_by`, `taxonomy_aliases`, `taxonomy_change_log`, `taxonomy_versions` 를 T09 에 추가 제안 |
| `skills (lower(name))` 인덱스 | 이름 검색 보조. 별칭 검색은 정규화된 `alias_norm` 으로 |
| `job_roles.description` (UI-006) | 표시 정보라 코드 정책과 무관 |


## 1. 왜 필요한가

같은 기술이 `Node.js`, `nodejs`, `노드`, `node js` 처럼 여러 이름으로 들어오면 검색·매칭·Skill Gap·공고 수집 결과가 흩어집니다. 이 정책은 **기술·직무마다 바뀌지 않는 코드 하나**를 두고, 다른 표기는 모두 그 코드로 모으는 규칙입니다.

## 2. 표준 코드 규칙

| 항목 | 규칙 | 예 |
|---|---|---|
| 형식 | 영문 대문자·숫자·밑줄, `^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$`, 64자 이하 | `PYTHON`, `SPRING_BOOT`, `BACKEND_ENGINEER` |
| 이름공간 | 기술(`skill`)과 직무(`job_role`)는 따로. 같은 철자라도 서로 섞이지 않음 | skill 에서 `python` 검색 → job_role 에는 없음 |
| 불변 | 한 번 만든 코드는 **바꾸지도, 지우지도, 다시 쓰지도 않음** | `CPP` → `CPLUSPLUS` 변경 금지 |
| 표시 이름 | `name_ko`·`name_en` 은 바꿀 수 있음 (코드는 그대로) | `노드JS` → `Node.js` |
| 특수문자 기술 | 기호 대신 뜻을 풀어 씀 | C++ → `CPP`, C# → `CSHARP`, .NET → `DOTNET` |
| 버전 | 기술 버전은 코드에 넣지 않음 (필요하면 별도 속성) | `PYTHON3` ✕ → `PYTHON` |

**코드 상태**

| 상태 | 뜻 | 새 입력 | 기존 데이터·API |
|---|---|:-:|---|
| `active` | 사용 중 | ○ | 정상 |
| `deprecated` | 더 이상 새로 쓰지 않음 (대체 코드 없거나 있음) | ✕ | 그대로 조회됨, 응답에 `deprecated: true` |
| `merged` | 다른 코드와 같은 것이라 합침 (`replaced_by` 필수) | ✕ | 옛 코드로 들어와도 살아 있는 코드로 바꿔서 응답 |

- 은퇴한 코드(`deprecated`·`merged`)는 다시 `active` 로 되돌리지 않습니다. 필요하면 새 코드를 만듭니다.
- 병합 체인(A→B→C)은 최대 5단계, **순환은 금지**합니다. 병합 대상은 반드시 `active` 여야 합니다.

## 3. 별칭(동의어) 규칙

| 항목 | 규칙 |
|---|---|
| 정규화 | 앞뒤 공백 제거 → 유니코드 NFKC → 소문자 → 공백·`.`·`-`·`_`·`/`·괄호 제거. **`+` 와 `#` 은 남김** (C++ ≠ C#) |
| exact 별칭 | 한 표기는 **코드 하나에만** 연결 (예: `k8s` → `KUBERNETES`, `파이썬` → `PYTHON`) |
| ambiguous 별칭 (다의어) | 한 표기가 여러 뜻이면 모든 후보에 연결하고 `ambiguous` 로 표시 (예: `Spring` → `SPRING_BOOT`, `SPRING_FRAMEWORK`). **자동으로 하나를 고르지 않음** |
| 혼합 금지 | 같은 표기를 exact 와 ambiguous 로 동시에 쓰지 않음 |
| 충돌 금지 | 별칭이 **다른 코드의 철자**와 같으면 거부 (예: `TypeScript` 를 `JAVASCRIPT` 별칭으로 등록 불가). 새 코드가 기존 별칭과 같아도 거부 |
| 병합 시 | 별칭은 살아 있는 코드로 옮김. 옮길 코드와 철자가 같은 별칭(예: `go lang` = `GOLANG`)이나 이미 있는 별칭은 정리 |
| 한글 표기 | 한글 별칭을 적극 등록 (예: `리액트`, `쿠버네티스`, `서버 개발자`) |

**조회 순서 (`resolve_term`)**
1. 입력을 정규화해서 **코드 철자**와 같으면 그 코드 (`match_type = code`)
2. 아니면 exact 별칭 (`alias`) 또는 ambiguous 별칭의 후보 전부 (`ambiguous`)
3. 찾은 코드가 병합됐으면 `replaced_by` 를 따라가 살아 있는 코드를 함께 돌려줌 (`canonical_code`, `is_deprecated`)
4. 없으면 `not_found`

| 사용처 | ambiguous 처리 |
|---|---|
| 자동완성·검색 (T139/T140) | 후보를 모두 보여주고 사용자가 고름 |
| 공고 자동 태깅 (T62/T138) | 자동 태깅하지 않고 검수 대기로 보냄 |
| 사용자 보유 기술 입력 | 반드시 코드로 저장 (별칭 문자열 저장 금지) |

## 4. 표준 출처

| 구분 | 방침 |
|---|---|
| 기본 | **자체 관리 목록** (T10 Seed 의 직무 30·기술 100 코드가 1.0.0 기준선 후보) |
| 외부 분류체계 | ESCO, O\*NET, 국가직무능력표준(NCS), 공공 직업분류 등은 **참고·매핑만** 하고 목록을 그대로 복제하지 않음. 쓰려면 라이선스·출처 표기 조건을 T61(데이터 출처·라이선스)에서 먼저 확인 |
| 외부 매핑 저장 | 필요해지면 `external_refs`(출처, 외부 ID, 확인일)를 별도 표로 둠 — 이번 범위 아님 |
| 공고에서 발견된 새 표기 | 바로 코드로 만들지 않고 큐레이터 검토 후 별칭 또는 새 코드로 등록 |

## 5. 버전과 변경 이력

- 분류체계 전체에 `MAJOR.MINOR.PATCH` 버전을 붙입니다.

| 변경 | 버전 | 호환성 |
|---|---|---|
| 별칭 추가, 표시 이름 수정 | PATCH | 영향 없음 |
| 코드 추가 | MINOR | 영향 없음 |
| 폐기·병합 | MAJOR | 옛 코드는 계속 조회됨. 저장된 데이터는 T138 배치로 살아 있는 코드로 옮김 |

- 모든 변경은 `taxonomy_change_log` 에 **버전·변경 종류·이유(5자 이상)·변경자·시각**과 함께 남깁니다. 이 이력은 수정·삭제할 수 없습니다.
- API 응답에 현재 분류체계 버전을 넣어, 클라이언트가 캐시를 갱신할 수 있게 하는 안을 제안합니다 (T139).

## 6. 권한

| 역할 | 할 수 있는 것 | 할 수 없는 것 |
|---|---|---|
| 조회 (`t137_reader`, 검색·매칭 API) | 코드·별칭·버전 조회, `resolve_term()` | 어떤 변경도 불가, 변경 이력 조회 불가 |
| 큐레이터 (`t137_curator`) | `add_code`, `add_alias`, `merge_code`, `deprecate_code`, `validate_taxonomy` 함수로만 변경 | 표에 직접 INSERT/UPDATE/DELETE |
| 소유자 (migrator) | 스키마 관리 | 코드 삭제·코드 값 변경·은퇴 코드 재활성화·이력 수정은 트리거가 막음 |

## 7. 정합성 검사 (`validate_taxonomy`)

다음이 하나라도 있으면 위반으로 보고합니다. CI 나 큐레이터가 변경 후 실행합니다.
- 병합된 코드가 가리키는 대상이 `active` 가 아님
- 별칭이 병합된 코드를 가리킴
- ambiguous 별칭인데 후보가 하나뿐
- 활성 코드끼리 영문 표시 이름이 정규화 후 같음

## 8. 검증 (일회용 DB 전용)

| 파일 | 내용 |
|---|---|
| [`database/tests/taxonomy/T137_code_taxonomy_mock.sql`](../../database/tests/taxonomy/T137_code_taxonomy_mock.sql) | 정책을 옮긴 mock 스키마 `taxonomy_mock` + T10 코드 기반 샘플 (Migration 아님) |
| [`database/tests/test_code_taxonomy.sh`](../../database/tests/test_code_taxonomy.sh) | 일회용 `postgres:18.1` 컨테이너에서 42개 항목 검증 |

```bash
D1_TEST_ONLY=YES bash database/tests/test_code_taxonomy.sh
```

| 구분 | 확인 항목 |
|---|---|
| 조회 | 대소문자 무시 코드 매칭, 한글 별칭, 공백·마침표 정규화(`Node . JS`), 짧은 별칭(k8s), C++·C# 구분, React·React Native 구분, 다의어(Spring) 후보 2개, 이름공간 분리, 없는 표기 |
| 거부 | 소문자·하이픈 코드, 중복 코드, 별칭과 같은 새 코드, 이미 쓰인 exact 별칭, 다른 코드 철자와 같은 별칭, exact·ambiguous 혼합, 없는 버전, 짧은 이유, 자기 자신 병합, 코드 삭제, 코드 값 변경 |
| 병합·폐기 | T05 `is_active` 가 상태를 따름(병합·폐기 → false), 옛 코드 → 살아 있는 코드 + deprecated 표시, 별칭 이동(`고랭`), 코드 철자와 같은 별칭 정리, 병합된 코드로 병합 거부, 순환 체인 거부, 병합 코드에 별칭 거부, 재활성화 거부, 대체 없는 폐기 |
| 이력·권한 | 변경 이력 5건 기록, 이력 수정·삭제 거부, 조회 계정의 변경·직접 INSERT·이력 조회 거부, 큐레이터의 직접 UPDATE·DELETE 거부 |
| 정합성 | `validate_taxonomy()` 위반 0건 |

테스트 중 실제 결함 1건을 찾아 고쳤습니다: 병합 때 별칭을 "복사 후 삭제"하면 exact 별칭 유일성 때문에 복사가 조용히 건너뛰어지고 원본만 지워져 별칭이 사라졌습니다. 지금은 별칭의 대상 코드를 바꾸는 방식으로 옮깁니다.

## 9. 미확정 항목 (PM·담당자 결정 필요)

1. T10 Seed 코드(직무 30·기술 100)를 1.0.0 기준선으로 승인할지
2. 외부 분류체계(ESCO/O\*NET/NCS) 매핑 여부와 라이선스 (T61)
3. 큐레이터 역할을 누가 맡는지, 변경 승인 절차(1인/2인)
4. 실제 테이블 반영 방식: T05 의 `is_active` 는 유지하고 `status`·`replaced_by` 컬럼 + 별칭·이력·버전 표를 추가할지 (T09 절차)
5. 병합 후 `user_skills`·`job_posting_skills` 등 저장 데이터를 옮기는 배치 주기 (T138)
6. 정규화 규칙에서 추가로 남길 기호가 있는지 (예: `F#`, `Objective-C`)
7. 직무 다의어(예: "엔지니어", "개발자" 단독 입력) 처리 기준

**판정:** `T137_STATUS=PARTIAL` — T05 B04/B05 기준 정책·mock 검증 PASS(로컬 42항목), 코드 기준선·변경 절차 PM 승인 전, T17 미완료로 실연동 HOLD.
