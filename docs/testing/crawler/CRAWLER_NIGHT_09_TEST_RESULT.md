# T61 검색 URL 지원 — 테스트 결과 (CRAWLER_NIGHT_09)

> 모든 HTTP 는 모의 응답입니다. 실제 JobKorea 요청은 **0 건**이며 Live 수집은 **BLOCKED** 그대로입니다.
> 이 결과는 URL 검사 기능 구현이 끝났다는 뜻입니다. 실제 수집 성공이 아닙니다.

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `crawler/policy/source_approval_gate.py` | 검색 URL 유형, `max_discovered_details`, `discovered_from`, 범위 판정 `_in_scope` |
| `crawler/jobs/import_jobkorea_html.py` | `_permit(..., discovered_from)`, 발견한 상세 URL 마다 출처 검색 URL 을 전달 |
| `crawler/jobs/night_crawl.py` | 모듈 docstring 만 수정(동작 변경 없음) |
| `crawler/tests/test_source_approval_gate.py` | T61 단위 테스트 13건 추가 |
| `crawler/tests/test_live_http.py` | HTTP 게이트 테스트 6건 추가, 2건 수정(검색 URL 우회 패치 제거) |
| `crawler/tests/test_night_crawl.py` | `live_gate` 테스트 2건 추가 |
| `crawler/tests/local_night_integration.py` | `_permit`·`live_gate` 패치 제거 → 실제 게이트 사용, AX 검색 → 발견 상세 2건 |
| `crawler/tests/staging_night_e2e.py` | `_permit`·`live_gate` 패치 제거 → 실제 게이트와 발견 범위 사용 |
| `docs/testing/crawler/CRAWLER_NIGHT_09_*.md` | 설계·결과 문서 |

## 2. 요구 시나리오 ↔ 테스트

| # | 시나리오 | 테스트 | 결과 |
|---|---|---|---|
| 1 | 승인된 검색 URL 통과 | `TestSearchAndDiscoveredScope.test_01` (`tabType` 유무, 한글 키워드) | PASS |
| 2 | 승인되지 않은 검색 URL 차단 | `test_02`, `GateTests.test_unlisted_keyword_search_sends_nothing` | PASS |
| 3 | 기존 상세 URL 통과 | `test_03`, `test_13`, 기존 26건 | PASS |
| 4 | 검색 결과의 상세 URL 처리 | `test_04`, `test_04b`, `test_04c`, `test_search_to_discovered_details_real_gate_and_request_accounting` | PASS |
| 5 | 외부 도메인 차단 | `test_05` (외부·유사 도메인, 사용자정보, 포트, http), 목록 안의 외부 링크 | PASS |
| 6 | 잘못된 공고번호 차단 | `test_06`, `test_04` (비 ASCII 숫자) | PASS |
| 7 | 과도·이상 쿼리 매개변수 차단 | `test_07` (15가지) | PASS |
| 8 | 승인 만료 차단 | `test_08` (만료·HOLD·비활성·승인 없음) | PASS |
| 9 | 목적 불일치 차단 | `test_09` | PASS |
| 10 | 요청 상한 초과 차단 | `test_10`, `test_job_budget_above_max_requests_sends_nothing`, `test_discovery_scope_smaller_than_job_budget_stops_before_details` | PASS |
| 11 | 승인 없는 요청 HTTP 0 건 | `GateTests.blocked()` 계열 (`_get` 호출 0 확인) | PASS |
| 12 | 리다이렉트 차단 | `test_redirects_are_never_followed`, `test_search_redirect_403_429_and_challenge_stop_the_job` | PASS |
| 13 | 기존 상세 URL 회귀 | `test_13`, 기존 `test_source_approval_gate` 26건, `test_live_http` 기존 테스트 | PASS |
| 14 | Fixture 경로 영향 없음 | `test_t154_*`, `test_offline_schedule`, `test_scheduler_policy` 무변경 통과. CI `local_t154_*`, `staging_night_e2e` 03:00 Fixture | 로컬 PASS, CI: 4절 |
| — | 403·429·CAPTCHA 중단 | `test_search_redirect_403_429_and_challenge_stop_the_job` (검색 페이지와 상세 페이지 모두) | PASS |
| — | 요청 수·간격 | 요청 순서 `robots → 검색 → 상세 2` 확인, `sleep ≥ 2` 3회 | PASS |
| — | 야간 키워드 6개 URL 이 정규형 | `test_every_night_keyword_search_url_is_canonical` | PASS |

## 3. 로컬 실행 결과 (Windows, Python 3.12, `.venv`)

```text
python -m unittest crawler.tests.test_source_approval_gate crawler.tests.test_live_http \
  crawler.tests.test_night_crawl crawler.tests.test_scheduler_policy crawler.tests.test_worker_collection_boundary
→ OK

python -m unittest discover -s crawler/tests
→ Ran 471 tests, skipped 5, errors 1
```

- 오류 1건은 `test_t155_read_models` 의 `ModuleNotFoundError: psycopg` 입니다. 로컬 venv 에 패키지가 없어서이며 **main 에서도 같습니다**.
- `backend/training_tests` 의 오류 4건도 로컬에 `fastapi` 가 없어서이며 main 과 같습니다.
- 로컬에서 `tzdata` 를 설치했습니다(Windows `Asia/Seoul`). 저장소 변경은 없습니다.

## 4. PostgreSQL 통합·E2E

로컬에는 Docker 가 없고, 로컬 PostgreSQL 의 기존 DB 는 건드리지 않았습니다. 그래서 PostgreSQL 통합과 E2E 는 **CI(`crawler-mvp.yml`, 일회용 postgres 서비스)** 결과를 근거로 합니다.

| 테스트 | 검증 내용 | 결과 |
|---|---|---|
| `local_night_integration` | **AX 검색 → 발견 상세 2건 → 파싱 → PostgreSQL INSERT → 키워드 관계 2건 → 체크포인트 1건**. 요청 순서·수 4, Slack 1회. 정확 나열 모드에서 429 중단, 나열되지 않은 상세는 요청 0 | PR CI 참조 |
| `staging_night_e2e` | 실제 `live_gate` 와 발견 범위로 하룻밤 6키워드, 03:00 Fixture 공존, 중복·UPDATE·체크포인트, 403/429/Timeout/파싱·저장 실패, 중단 복구, Slack 라벨 | PR CI 참조 |
| `local_t64_*`, `local_t152_*`, `local_t154_*`, `local_t155_*`, `local_html_pg_integration` | 기존 회귀 | PR CI 참조 |

CI 결과(run 번호와 결론)는 PR 본문과 코멘트에 기록합니다. CI 를 확인하기 전에는 PASS 로 표시하지 않습니다.

## 5. 미완료 항목

- 실제 JobKorea 수집: **BLOCKED**
  - T61 HOLD, 승인 기록 없음, 서버 환경변수 3개 UNSET
  - `/Search` 경로의 robots·약관 검토가 아직 없습니다
- Staging 반영:
  - 병합 후 Auto-CD 로 backend 이미지에 포함됩니다
  - Staging 동작은 바뀌지 않습니다. 야간 경로는 `CRAWLER_NIGHT_ENABLED` UNSET 이라 `DISABLED`
- 독립 리뷰와 병합: PR 에서 진행합니다. 병합은 PM 이 합니다.

## 6. Live 수집 상태

`LIVE_COLLECTION=BLOCKED`, `LIVE_HTTP_REQUESTS=0`, `STAGING_CHANGED=NO`, `PRODUCTION_CHANGED=NO`.
