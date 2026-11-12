# 실제 JobKorea 수집 1회 검증 결과 (CRAWLER_NIGHT_08)

> 판정: **BLOCKED**. 실제 HTTP 요청은 **0 건**입니다. robots.txt 도 요청하지 않았습니다.
> 실행 전 점검에서 T61 게이트가 차단했으므로 Live 수집을 시작하지 않았습니다. 게이트 우회, 승인 기록 생성, 환경변수 변경은 하지 않았습니다.

## 1. 실행 정보

| 항목 | 값 |
|---|---|
| 점검 일시 | 2026-11-12 21:56 KST (Staging 읽기 전용) |
| main / Staging SHA | `d5dd380` / `d5dd380` (Auto-CD deploy-end PASS, 이후 UNCHANGED) |
| 대상 키워드 | `AX` (`search_keywords.keyword_id=37`, enabled) |
| Live 실행 | **하지 않음** |
| 실제 HTTP 요청 | **0** (검색 목록 0, 상세 0, robots.txt 0) |
| 목록·상세 응답 | 없음 (요청하지 않음) |
| 파싱 성공·실패 | 해당 없음 |
| 신규·수정·중복 | 0 / 0 / 0 |

## 2. 차단 조건

필요한 조건을 하나씩 확인했습니다. 하나만 빠져도 수집은 시작되지 않습니다.

| # | 조건 | 상태 | 근거 |
|---|---|---|---|
| 1 | `CRAWLER_NIGHT_ENABLED=1` (야간 경로) | **UNSET** | backend 컨테이너 환경. 서버 `.env` 와 overlay 에도 정의 없음 |
| 2 | `CRAWLER_LIVE_SCHEDULE_APPROVED=1` | **UNSET** | 같음 |
| 3 | `CRAWLER_NIGHT_POLICY_FILE` | **UNSET** | 같음 |
| 4 | T61 승인 파일(`approval_status=APPROVED`) | **없음** | 서버 `/home/kant` 아래 `approval_status` 를 가진 JSON 0 건(메타데이터만 확인) |
| 5 | T61 범위가 검색 URL 을 허용 | **구조적으로 불가** | 아래 3절 |
| 6 | T61 정책 상태 | **HOLD** | `docs/data/SOURCE_REGISTRY.md`, `T61_STEP05_JOBKOREA_ROBOTS_REVIEW.md`: `candidate_jobkorea=HOLD`, `LIVE_COLLECTION=HOLD` |

가장 직접적인 원인은 5번입니다. 1~4번은 운영 설정으로 풀 수 있습니다. 5번은 코드와 T61 결정이 바뀌어야 합니다.

## 3. T61 게이트가 검색 URL 을 막는 이유

`crawler/policy/source_approval_gate.py` 의 `check_collection_permission` 은 다음을 요구합니다.

- 요청 URL 이 `_canonical_jobkorea()` 형식, 즉 `https://www.jobkorea.co.kr/Recruit/GI_Read/<숫자>` 여야 합니다.
- `allowed_urls` 의 모든 항목도 그 형식이어야 합니다.
- 요청 URL 이 `allowed_urls` 에 그대로 들어 있어야 합니다.

검색 URL `https://www.jobkorea.co.kr/Search/?stext=AX&tabType=recruit` 은 이 형식이 아니므로 승인 내용과 무관하게 `OUT_OF_SCOPE` 가 됩니다.

main 의 게이트 함수를 로컬 메모리에서만 호출해 확인했습니다. 파일·DB 기록은 만들지 않았고 네트워크 요청도 없습니다.

| 입력 | 결과 |
|---|---|
| 검색 URL 을 `allowed_urls` 에 넣은 APPROVED 승인 | `OUT_OF_SCOPE` |
| 검색 URL + 상세 URL 을 넣은 APPROVED 승인 | `OUT_OF_SCOPE` |
| 상세 URL 만 넣은 승인, 상세 URL 요청 | `ALLOWED` |
| 승인 없음 (현재 서버 상태) | `NOT_APPROVED` |

상세 URL 도 정확한 GI_Read URL 이 `allowed_urls` 에 미리 있어야 합니다. 그런데 검색 결과에서 나올 상세 URL 은 검색 페이지를 받기 전에는 알 수 없습니다. 따라서 **`AX` 검색 → 상세 → 저장 흐름은 지금의 T61 계약으로는 어떤 승인 파일로도 통과할 수 없습니다.**

## 4. 요청이 0 건이라는 근거

- `crawler/jobs/import_jobkorea_html.py` 의 `fetch_pages()` 는 `_permit()`(T61 검사)을 `robots.txt` 요청보다 먼저 실행합니다. 게이트가 막으면 어떤 HTTP 도 나가지 않습니다.
- `crawler/jobs/night_crawl.py` 의 `run_night_step()` 은 `CRAWLER_NIGHT_ENABLED!='1'` 이면 즉시 `DISABLED` 를 반환합니다. 21:00 이후 Staging dispatcher 로그는 모두 `night=DISABLED`, `external_requests=0` 입니다.
- 이번 작업에서 Live 진입점(`import_jobkorea_html` live, `dispatcher` 야간 단계)을 직접 실행하지 않았습니다.

## 5. 수집을 가능하게 하는 최소 조치 (PM·T61 결정 필요)

**A. 키워드 검색 흐름 (요청한 검증 범위)**

1. 코드 PR: T61 게이트가 정확히 하나의 정규 검색 URL(`/Search/?stext=<키워드>&tabType=recruit`)을 명시 승인으로 받도록 합니다. 그 검색 결과에서 나온 GI_Read 상세 URL 은 `max_requests` 와 `DETAIL_LIMIT` 안에서 허용합니다. 독립 리뷰와 CI 를 거칩니다.
2. T61 결정: JobKorea `/Search` 경로의 robots·약관 검토와 `HOLD` 해제. 현재 robots 검토 문서는 `/Recruit/GI_Read/` 만 다룹니다.
3. 서버 운영 설정(PM 승인 후):
   - 승인 파일 배치
   - `CRAWLER_LIVE_SCHEDULE_APPROVED=1`, `CRAWLER_NIGHT_POLICY_FILE`
   - 1회 실행에 쓸 진입점
   
   야간 자동 반복을 켜지 않으려면 `CRAWLER_NIGHT_ENABLED` 는 끈 상태로 둡니다. 그 대신 `import_jobkorea_html --list-url ... --limit 5 --policy-file ...` 을 한 번 실행합니다.

**B. 오늘 코드로 가능한 범위 (검색 단계 제외)**

- PM 이 정확한 GI_Read 상세 URL 최대 5개를 승인 파일에 넣으면 `import_jobkorea_html --url ... --policy-file ...` 로 상세 수집 1회가 가능합니다.
- 다만 이 경로는 다음을 검증하지 못합니다.
  - 키워드 검색과 `AX` 연결
  - 야간 작업 이력(`night_job_results`)
  - 야간 Slack 알림

  따라서 이번 단계의 목표 흐름과 다릅니다.

## 6. 최종 판정

`FINAL_STATUS=BLOCKED`.
- Live 게이트는 BLOCKED 입니다. 환경변수 3개 UNSET, 승인 파일 없음, 검색 URL 은 T61 범위 밖입니다.
- 실제 요청은 0 건이며 수집·저장·Slack 은 발생하지 않았습니다.
- 기존 E2E(CRAWLER_NIGHT_07, `e2e-5abde009`, 7/7)는 모의 HTTP 결과입니다. 실제 수집 성공으로 보지 않습니다.
