# T139 검증 보고서 — 기술 자동완성·동의어 검색 API

## 1. 작업 목적
동의어(한글·영문·줄임말)를 표준 기술 코드로 바꿔 주는 자동완성 API를 만듭니다. 승인 전 기능이므로 서버 플래그 `SKILL_AUTOCOMPLETE_API`(기본 `false`) 뒤에 둡니다. 계약·규칙은 `docs/api/T139_SKILL_SUGGEST_API.md` 에 있습니다.

## 2. 기존 구현·PR 재사용
- T17 `GET /skills`(#117)는 **변경하지 않았습니다**. 공개 조회 방식, HMAC cursor, `derive_key`, `career.skills` 를 재사용했습니다.
- T137 정책(#37) §3의 정규화·일치 순서·다의어 규칙을 그대로 옮겼습니다. PostgreSQL `normalize_term()` 과 결과가 같은지 시험합니다.
- T138 PR #154(김예주, OPEN)와 겹치는 파일은 없습니다. T138이 비활성화한 코드는 `is_active=false` 로 후보에서 빠집니다.
- T129 패턴(플래그·`AttemptLimiter`), T111 환경 계약(`env_contract.py`, `ENVIRONMENT_MATRIX.md`, `.env.example`)을 재사용했습니다.

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16` (main)
- HEAD_SHA: PR 댓글에 기록합니다(이 보고서를 포함한 커밋 뒤에 확정).

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `backend/app/services/skill_suggest.py` | 정규화, 일치·정렬·중복 제거, 병합 해석(최대 5단계), 서명 cursor |
| `backend/app/repositories/skill_suggest.py` | 실제 `career.skills` 활성 기술 SELECT (최대 5001행) |
| `backend/app/routers/skill_suggest.py` | `GET /api/v1/skills/suggest`, IP 당 요청 한도 |
| `backend/app/core/config.py`, `backend/app/main.py` | 플래그(기본 꺼짐)와 조건부 등록 |
| `backend/app/core/env_contract.py`, `.env.example`, `docs/ops/ENVIRONMENT_MATRIX.md` | T111 계약에 플래그 추가 |
| `database/proposed/T139_skill_suggest_index.sql` | 제안 인덱스(적용 안 함) |
| `backend/tests/test_t139_skill_suggest.py` | 37건 |
| `docs/api/T139_SKILL_SUGGEST_API.md`, 이 보고서 | 계약·검증 |

## 5. 선행조건
| 선행 | 상태 | 영향 |
|---|---|---|
| T17 | 병합 | 사용 |
| T98 | 병합(PROPOSED 계약) | 직접 의존 없음 |
| T137 | 병합. 리뷰 수정 #129 OPEN | 정책만 사용. **별칭 표 migration 없음** → 실제 DB 동의어 변환 HOLD |
| T138 | **#154 OPEN** | 직접 의존 없음 |

## 6. 실제 실행 명령
```bash
cd backend
# 단위·HTTP·PostgreSQL (일회용 PG 18.6, loopback, t16_profile_test)
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://<로컬 관리자>@127.0.0.1:<port>/t16_profile_test \
  python -m pytest -q tests/test_t139_skill_suggest.py
# 전체 회귀
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=... python -m pytest -q
# API 호환(T116)
BASE_REF=origin/main python docs/api/check_compat.py
# 로컬 실제 API: 일회용 DB(0001~0003 + T10 seed) + uvicorn, SKILL_AUTOCOMPLETE_API=true
curl "http://127.0.0.1:8139/api/v1/skills/suggest?q=python&limit=3"
```

## 7. 정상·오류·권한 검증
| 구분 | 확인 내용 | 결과 |
|---|---|---|
| 정규화 | `Node . JS`→`nodejs`, C++/C# 구분, 전각 `Ｐｙｔｈｏｎ`, 괄호·슬래시, 한글 공백 (10건) + SQL 결과와 동일 | PASS |
| 동의어→표준 코드 | `파이썬`→PYTHON, `k8s`·`쿠버네티스`→KUBERNETES, `JS`, `postgres` (합성 분류) | PASS |
| 다의어 | `Spring` → SPRING_BOOT·SPRING_FRAMEWORK 둘 다, 자동 선택 없음 | PASS |
| 병합·폐기 | `React.js`·옛 코드 `REACTJS` → REACT(alias), jQuery(deprecated) 제외, 순환·7단계 체인 제외(멈추지 않음) | PASS |
| 중복 제거·정렬 | `react` → REACT(code), REACT_NATIVE(prefix) 한 번씩 | PASS |
| 입력 중 한글 | `리액`→REACT(prefix), `설계`→REST_API(partial) | PASS |
| 잘못된 입력 | 빈 값, `---`, 제어 문자, 61자, limit 0·51 → 422 `VALIDATION_FAILED` | PASS |
| 페이지 | limit 1·2·3·50 으로 끝까지 중복·누락 없음, 다른 검색어·변조·다른 키·데이터 변경 cursor → 400 | PASS |
| 남용 | IP 당 한도 초과 → 429 | PASS |
| 플래그 | 꺼짐: 404, OpenAPI 에 경로 없음 | PASS |
| 인증 | 공개 조회. 잘못된 `Authorization` 도 200(T17 과 같음). 응답에 status·replaced_by 등 내부 필드 없음 | PASS |
| 출처 크기 | 5001행 → 503 | PASS |
| 성능 | 합성 5000항목 질의 평균 약 34 ms(로컬) | PASS(로컬 측정) |

## 8. PostgreSQL / Mock / 실제 API 구분
| 구분 | 범위 | 결과 |
|---|---|---|
| 합성 분류(메모리) | 동의어·다의어·병합·폐기 | PASS |
| PostgreSQL 18.6 일회용 | 실제 0001~0003 + T10 Seed, 최소 권한 앱 역할(SELECT만), HTTP 경유. code·prefix·partial, C++/C#, 비활성 제외, 전체 페이지 순회, 데이터 변경 없음 | PASS |
| 실제 DB 동의어 | `파이썬` → 빈 결과(별칭 표 없음) — **기능 한계를 시험으로 고정** | HOLD |
| 로컬 실제 API(uvicorn) | `python`→PYTHON(code, skill_id 포함), `파이썬`→빈 결과, `---`→422, 접근 로그에 검색어 미기록(`?[query redacted]`, T112) | PASS |
| 인덱스 | 제안 DDL 적용 가능. 기본 계획은 Seq Scan, 강제 시에만 인덱스 사용 → 현재 불필요 | 기록 |
| Staging | 실행 안 함 | NOT_RUN |

로컬 전체 회귀(Windows, 일회용 PG): 1676 passed, 101 skipped, 1 failed + 31 errors. 실패 1건과 오류 31건은 모두 `test_documents.py`·`test_security_upload.py` 로, main 에서도 같은 Windows POSIX 권한(0700) 관련 기존 실패입니다. 처음 실행 때 실패하던 T111 매트릭스 시험은 `ENVIRONMENT_MATRIX.md` 에 플래그 행을 넣어 고쳤습니다(시험은 바꾸지 않음).

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- T137 별칭·상태 표 migration 미승인 → 실제 DB 동의어 변환 불가(HOLD)
- T138 #154 미병합
- 계약 미승인 → `openapi.yaml` 미반영, 플래그 기본 꺼짐

## 11. 후속 작업
- PM 승인 후 openapi.yaml·Frontend 생성 타입 반영
- T137 별칭 표 migration 시 `SqlSkillSource` 에 별칭 JOIN 추가 + `alias_norm` 인덱스
- 직무 코드 자동완성(직무 다의어 규칙 결정 후)
- T140(UI)이 이 API 를 사용합니다(스택 PR)

```text
UNIT_TESTS=PASS
POSTGRESQL_TESTS=PASS
FRONTEND_TESTS=NOT_RUN
BROWSER_E2E=NOT_RUN
MOCK_VALIDATION=PASS
REAL_API_VALIDATION=PASS (local isolated; real-DB synonyms HOLD)
STAGING_VALIDATION=NOT_RUN
```
