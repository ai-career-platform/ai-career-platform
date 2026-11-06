# 개발·QA 합성 데이터 공장 (T147)

> 상태: **DRAFT**. 로컬·CI·테스트용 일회용 DB 전용입니다. 공유 Staging 적용 금지 (T12 승인 대상 아님).
> 대상 스키마: **T05 데이터 사전 v0.2** 검증용 DDL (`python3 database/model/check_data_dictionary.py --ddl`)
> 작업지시서: [T147](../../docs/work-orders/fifth-30/T147.md)

T10 Seed(고정된 기준 데이터)와 달리, 이 공장은 **원하는 규모의 합성 데이터를 시드값으로 언제나 똑같이** 만들어 줍니다. 성능·부하·QA 시나리오처럼 데이터가 많이 필요할 때 씁니다.

## 파일

| 파일 | 내용 |
|---|---|
| `synth_factory.py` | 표준 라이브러리만 쓰는 생성기. SQL 과 AI 피처(JSONL)를 만듭니다 |
| `../tests/test_synth_factory.py` | DB 없이 도는 단위 테스트 16개 (결정성·무결성·거부·환경 격리) |
| `../tests/test_synth_factory_db.sh` | 일회용 `postgres:18.1` 에 T05 DDL → 생성 SQL 2회 적용 → 건수·지문·가드 확인 |

## 사용법

```bash
python3 database/fixtures/synth_factory.py --target-env local --seed 147 \
  --users 300 --companies 40 --postings 500 \
  --out-sql /tmp/synth.sql --out-features /tmp/features.jsonl
psql -X -v ON_ERROR_STOP=1 -d <로컬_test_DB> -f /tmp/synth.sql
```

마지막 줄에 `T147_FACTORY seed=… sha256=… counts={…}` 가 찍힙니다. 같은 시드·규모면 sha256 이 항상 같습니다.

| 옵션 | 범위 | 기본값 |
|---|---|---|
| `--target-env` | `local` / `ci` / `test` 만 허용 | (필수) |
| `--seed` | 정수 | 147 |
| `--users` | 1~5000 | 200 |
| `--companies` | 1~1000 | 30 |
| `--postings` | 0~20000 | 300 |

## 만드는 데이터

| 테이블 | 규칙 |
|---|---|
| `data_sources` | `synthetic_seed` 하나 (T10 과 같은 고정 ID, 이미 있으면 그대로 사용) |
| `job_roles`, `skills` | `SYN_ROLE_01`~`12`, `SYN_SKILL_001`~`030` — T10 기준 코드와 **겹치지 않게** `SYN_` 접두어 |
| `job_role_skills` | 직무마다 기술 5개, 요구 수준 5→1 |
| `companies` | `합성기업 <seed>-0001`, `https://c0001.s<seed>.example.test` |
| `users`, `user_profiles` | `synth-<seed>-00001@example.test`(= `email_canonical`), 약 5% `disabled`, active 만 프로필 |
| `user_skills` | 사용자마다 목표 직무의 기술 3개, 숙련도 1~5 |
| `job_postings`, `job_posting_skills` | published 80% / draft·closed 각 10%, 공고마다 직무 상위 기술 4개 |
| `user_job_bookmarks` | active 사용자가 published 공고만 0~3개 |
| AI 피처 JSONL | `entity_id`, `target_role`, `skills{코드: 숙련도}`, `dataset_version`, `source` — 개인정보 없음 |

## 안전장치 (환경 격리·민감정보)

| 장치 | 동작 |
|---|---|
| `--target-env` 허용 목록 | `local`/`ci`/`test` 외에는 파일을 만들지 않고 종료 코드 2 |
| `CAREER_ENV` 환경변수 | `staging`·`stage`·`prod`·`production`·`live` 가 들어 있으면 거부 |
| SQL 첫 줄 가드 | DB 이름에 `test`/`ci`/`local`/`tmp`/`dev` 가 없거나 `staging`/`prod`/`live` 가 있으면 SQL 이 스스로 중단 |
| 생성 직후 검증 | T05 규칙(유일·FK·상태값·숙련도 1~5·published 날짜·비교용 이메일)을 Python 에서 먼저 확인 |
| 민감정보 검사 | `example.test` 외 이메일, 휴대전화번호, 주민등록번호, 카드번호 형태가 하나라도 있으면 실패 (UUID 안의 숫자는 제외) |
| 재실행 | `ON CONFLICT DO NOTHING` 이라 두 번 넣어도 그대로 |

## 검증 결과 (로컬, PostgreSQL 16.2)

- 단위 테스트 16개 PASS, 시드 1~200 으로 생성해도 민감정보 오탐 0
- DB 테스트: T05 DDL 에 300명·40개 기업·500개 공고 적용 → 모든 행 저장, 2회차 변화 없음, `career_staging` 이름 DB 에서 거부
- T10 Seed 와 같은 DB 에 어떤 순서로 넣어도 FK 충돌 없음 (출처를 코드로 공유)

## 미확정·후속 항목

- 선행 일감 T11(제약·인덱스 테스트)·T87(동의 철회 E2E)·T115(환경별 Migration 검증)는 진행 중입니다. 그 결과에 맞춰 생성 규칙(예: 동의·문서 데이터)을 늘려야 합니다.
- 동의·문서·추천 등 나머지 T05 테이블은 담당 일감의 규칙이 정해진 뒤 추가합니다.
- CI 워크플로에 이 테스트를 넣는 일은 공용 워크플로 파일을 고치게 되어 이번에는 하지 않았습니다 (`python3 -B -m unittest discover -s database/tests -p "test_synth_factory.py"` 한 줄 추가로 가능).
