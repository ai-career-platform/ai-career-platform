# T61 검색 URL·발견 상세 URL 검사 설계 (CRAWLER_NIGHT_09)

> 상태: 구현·테스트 완료. **승인 기록 없음 / T61 HOLD 유지 / Live BLOCKED / 실제 JobKorea 요청 0 건.**
> 이 변경은 "URL 유형을 검사할 수 있다"는 뜻입니다. 수집을 승인한다는 뜻이 아닙니다. 승인 여부는 기존 게이트(상태·기간·근거·목적·요청 상한)가 그대로 판정합니다.

## 1. 기존 게이트의 문제

| # | 문제 | 위치 |
|---|---|---|
| 1 | URL 형식 검사가 `https://(www.)jobkorea.co.kr/Recruit/GI_Read/<숫자>` 하나뿐 | `_canonical_jobkorea()` |
| 2 | `allowed_urls` 의 모든 항목이 그 형식이어야 해서 검색 URL 을 승인 기록에 넣으면 기록 전체가 무효 | `check_collection_permission()` |
| 3 | 검색 결과의 상세 URL 은 검색 페이지를 받아야 알 수 있는데, 게이트는 상세 URL 을 미리 정확히 나열하도록 요구 | 같음 |
| 4 | 그래서 테스트 하네스가 검색 URL 에 대해 `_permit` 을 패치해 통과시켰음 | `local_night_integration.py`, `staging_night_e2e.py`, `test_live_http.py` |

## 2. 변경 요약 (최소 변경)

변경은 `crawler/policy/source_approval_gate.py` 와 호출부 한 곳뿐입니다.

1. **검색 URL 유형 `_canonical_jobkorea_search()`**: 키워드 검색 URL 형식을 검사합니다(3절).
2. **`allowed_urls` 허용 형식 확장**: `allowed_urls` 에 검색 URL 과 상세 URL 을 모두 넣을 수 있습니다. 요청 URL 은 여전히 **목록과 문자열이 정확히 같아야** 통과합니다.
3. **`SourceApproval.max_discovered_details: int = 0`(새 필드, 기본 꺼짐)**: 1~5 로 설정하면, 승인된 검색 페이지에서 발견한 `GI_Read` 상세 URL 을 미리 나열하지 않아도 제한적으로 허용합니다(4절).
4. **`CollectionIntent.discovered_from: str | None = None`(새 필드)**: 이 상세 URL 을 어느 검색 페이지에서 찾았는지 담습니다. 값은 `fetch_pages()` 만 넣습니다.
5. **`import_jobkorea_html.fetch_pages()`**: 발견한 각 상세 URL 을 `_permit(..., discovered_from=list_url)` 로 **하나씩** 검사합니다. 이것이 유일한 호출부 변경입니다.

`night_crawl.live_gate`, `scheduler.eligible`, admin 명령 경로는 수정하지 않았습니다.

## 3. 검색 URL 검사

허용 형식은 **두 가지 철자뿐**입니다.

```text
https://www.jobkorea.co.kr/Search/?stext=<quote(키워드)>
https://www.jobkorea.co.kr/Search/?stext=<quote(키워드)>&tabType=recruit   ← night_crawl.search_url() 형식
```

| 검사 | 차단 예 |
|---|---|
| HTTPS 만 | `http://…` |
| 호스트는 정확히 `www.jobkorea.co.kr` (netloc 일치, 사용자정보·포트 없음) | `jobkorea.co.kr`, `www.jobkorea.co.kr.evil.org`, `user@…`, `:443` |
| 경로는 정확히 `/Search/` (대소문자 구분) | `/Search`, `/search/` |
| 쿼리 매개변수는 `stext` 와 선택적 `tabType=recruit` 만, 이 순서로 | `&page=2`, `stext` 중복, 순서 바뀜, `tabType=corp` |
| 검색어 필수: 공백만 있거나 100자 초과, 제어문자 금지 | `stext=`, `stext=%20`, `%0A` |
| **정규 인코딩만**: 원래 쿼리가 `quote()` 로 다시 만든 쿼리와 같아야 함 | `%41X`(=AX), `A+X`, 인코딩 안 된 한글 |
| fragment 금지 | `#top` |

정규 철자를 하나로 고정했습니다. 그래서 같은 키워드를 다른 철자로 써서 `allowed_urls` 의 정확 일치 검사를 우회할 수 없습니다. `night_crawl.search_url()` 이 만드는 야간 키워드 6개 URL 은 모두 이 형식을 통과합니다(테스트로 확인).

**검색 범위 판정**은 기존과 같은 정확 일치입니다. 승인 기록의 `allowed_urls` 에 해당 검색 URL 이 그대로 있어야 합니다. 와일드카드나 키워드 패턴은 지원하지 않습니다.

## 4. 발견한 상세 URL 검사

`fetch_pages(list_url=검색URL)` 의 흐름입니다.

1. 검색 URL 을 게이트로 검사합니다(`requested_calls = robots 1 + 검색 1 + limit`). 실패하면 **robots.txt 를 포함해 어떤 요청도 보내지 않습니다**.
2. robots.txt 를 받고, 검색 목록 HTML 을 받습니다(robots 검사, 2초 이상 간격).
3. `parse_jobkorea_list_html(limit)` 으로 상세 URL 을 최대 `limit` 개 추출합니다. 정규형 `GI_Read` 링크만 추출됩니다.
4. **추출한 URL 마다 게이트를 다시 실행합니다**(`discovered_from=검색URL`). 하나라도 실패하면 `FetchBlocked('UNAPPROVED_SOURCE')` 로 작업을 멈추고 상세 요청은 0 건입니다(fail-closed).
5. 통과한 상세만 요청 → 파싱 → 정규화 → `upsert` → 키워드 관계·체크포인트 순으로 처리합니다.

발견한 상세 URL 은 아래 **모두**를 만족해야 통과합니다.

- `discovered_from` 이 정규 검색 URL 이고 `allowed_urls` 에 정확히 있음. 승인된 검색 페이지에서 나온 링크만 대상입니다.
- 상세 URL 이 정규 `GI_Read/<ASCII 숫자>` 형식임. 다른 경로, 외부 호스트, 쿼리, 비 ASCII 숫자는 차단합니다.
- 그리고 다음 중 하나:
  - **(a) 정확 나열**: 상세 URL 이 `allowed_urls` 에 있음. 기존 방식이며 `max_discovered_details=0` 이어도 동작합니다.
  - **(b) 제한 발견**: `1 ≤ max_discovered_details ≤ 5` 이고, `requested_calls ≤ 2 + max_discovered_details`.
- 그 밖의 기존 검사(승인 상태, enabled, 근거, 유효기간, 목적, 방법, `requested_calls ≤ max_requests`, 사용 정책)도 모두 통과해야 합니다.

**검색 URL 이 승인되었다고 그 페이지의 링크가 일괄 허용되지는 않습니다.** 링크마다 별도 판정합니다. 허용 범위는 "승인된 검색 페이지 1개 × `GI_Read` 경로 × 최대 5건"입니다. 사이트 전체 와일드카드는 없습니다.

`max_discovered_details` 가 정수가 아니거나(`True`, `"5"`, `None` 포함) 0~5 범위를 벗어나면 승인 기록 전체를 `INVALID_POLICY` 로 처리합니다.

## 5. 요청 수 제한

| 항목 | 적용 |
|---|---|
| 예산 산정 | `fetch_pages`: `calls = 1(robots) + 1(검색) + limit`. 야간 작업은 `limit=DETAIL_LIMIT=5` → 7 |
| 승인 상한 | 검색·상세 모든 판정에서 `requested_calls ≤ max_requests` |
| 발견 상한 | `requested_calls ≤ 2 + max_discovered_details`. 승인된 발견 수보다 큰 작업은 상세 요청 전에 차단 |
| 작업당 상세 | `parse_jobkorea_list_html(limit)` 와 `DETAIL_LIMIT=5` |
| 간격 | `_fetch_allowed`: `max(2초, robots crawl-delay)` |
| 동시 실행 | 기존 dispatcher advisory lock(1개). 변경 없음 |
| 기록값 | 기존 F-08 `_bounded` 계측(실패 시 상한으로 계산, 과소 기록 금지). 변경 없음 |

## 6. 보안·실패 처리

- **리다이렉트**: `_NoRedirect` 로 따라가지 않습니다. 3xx 는 `FetchBlocked(HTTP_3xx)` 로 작업을 중단합니다. 리다이렉트 목적지로는 요청이 나가지 않습니다.
- **403·429·401**: `FetchBlocked` 로 즉시 중단합니다. 야간 작업은 `STOP_CODES` 로 그날 밤을 멈춥니다.
- **CAPTCHA·접근 제한 문구**: `ACCESS_CHALLENGE` 로 중단합니다.
- **Timeout**: 기존 `RETRYABLE_CODES` 와 `MAX_ATTEMPTS=3` 를 적용합니다.
- **승인 없음·HOLD·만료·비활성·목적 불일치·상한 초과·형식 이상**: 게이트가 막으며 HTTP 요청은 0 건입니다.

## 7. 기존 상세 URL 호환성

- `max_discovered_details` 가 없는 기존 승인 기록은 기본값 0 이 되어 **전과 똑같이 동작**합니다. 상세 URL 은 정확 나열만 통과합니다.
- `scheduler.eligible`(일일 Live 스케줄)은 `target_urls` 상세 URL 만 쓰므로 영향이 없습니다. Fixture 경로는 게이트를 거치지 않으므로 영향이 없습니다.
- 기존 T61 단위 테스트 26건은 수정 없이 통과합니다.

## 8. 바뀌지 않은 것

- 서버 환경변수 3개(`CRAWLER_NIGHT_ENABLED`, `CRAWLER_LIVE_SCHEDULE_APPROVED`, `CRAWLER_NIGHT_POLICY_FILE`): UNSET 그대로
- 승인 파일: 없음. T61 `candidate_jobkorea=HOLD` 그대로
- 03:00 Fixture 스케줄, Dispatcher Timer, Staging DB, Production: 변경 없음

실제 수집을 하려면 다음이 필요합니다.
- T61/PM 결정: `/Search` 경로의 robots·약관 검토와 HOLD 해제
- 승인 기록: 대상 검색 URL 과 `max_discovered_details`
- 서버 설정
