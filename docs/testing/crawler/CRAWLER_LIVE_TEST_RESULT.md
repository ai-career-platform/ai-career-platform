# Staging 제한 Live 크롤링 1회 검증 (CRAWLER_LIVE_TEST_01)

> 2026-11-12 · 판정: **BLOCKED** — T61 출처 승인 게이트가 충족되지 않아 Live 수집을 실행하지 않았습니다.
> JobKorea 로 보낸 HTTP 요청은 0건입니다(robots.txt 포함). Fixture 결과를 실데이터 수집으로 대체하지 않았습니다.

## 1. 기존 Live 경로

| 진입점 | Live 조건 | 현재 Staging |
|---|---|---|
| T64 `dispatcher dispatch`(스케줄) | ① `schedules.mode='live'` ② `CRAWLER_LIVE_SCHEDULE_APPROVED=1` ③ 대상 URL 1~5개(정규 `GI_Read/<숫자>`) ④ 유효한 T61 승인 기록이 모든 URL·목적(`scheduled_collection`)·기간·요청 수를 허용 (`scheduler.eligible` → `check_collection_permission`) | ① fixture ② 미설정 ③ 0개 ④ 승인 기록 없음 → **차단** |
| `dispatcher manual-fixture`(#250) | Fixture 만 허용. live 면 `MANUAL_FIXTURE_ONLY` 로 거부 | Live 수집 경로가 아님 |
| `crawler.jobs.import_jobkorea_html --url/--list-url`(#85) | robots 검사, 15초 timeout, 2초 이상 간격, 최대 10건, 403/429/CAPTCHA/redirect 중단. **T61 승인 게이트를 거치지 않음** | 사용하지 않음(아래 §2) |
| `run_crawler --collection-mode live_jobkorea` | 항상 거부(T61 STEP 09 경계) | - |

## 2. T61 정책·승인 상태

- `docs/data/SOURCE_REGISTRY.md`: `candidate_jobkorea = HOLD`, `enabled=false`
- `crawler/policy/T61_STEP08_APPROVAL_GATE.md`: `REAL_APPROVAL=HOLD`. PM/제공자 승인 없이 `APPROVED` 정책 객체를 만들지 않습니다.
- `crawler/policy/T61_STEP10_EVIDENCE_REVIEW.md`: 권한 문의 `DRAFT_NOT_SENT`, 공식 회신 `NOT_RECEIVED`
- `source_approval_gate.py` 주석: "현재 유효한 JobKorea 승인 기록이 없으며, 만들어 내지 말 것"
- 이전 PM 지시(DAILY_CRAWLER_AUDIT_04): "Live 수집 활성화는 승인하지 않는다"

**결론**
- 승인 게이트를 통과하는 실행 경로가 없습니다.
- `import_jobkorea_html` 은 게이트 없이 Live HTTP 를 보낼 수 있습니다. 이번 지시("승인되지 않은 Live 수집 게이트는 우회하지 마세요")에 따라, 이 경로로 수집하는 것도 게이트 우회로 판단해 실행하지 않았습니다.
- 승인 기록을 임의로 만들거나 환경변수·스케줄을 바꾸지 않았습니다.

## 3. 결과

| 항목 | 값 |
|---|---|
| LIVE_HTTP_REQUESTS | 0 |
| FETCHED / PARSED | 0 / 0 |
| INSERTED / DUPLICATES / FAILED | 0 / 0 / 0 |
| DB | 변경 없음. 같은 날 19:05 KST 조회 기준 공고 35(2/28/5), runs 2, run_events 8 |
| Slack | 실행이 없으므로 알림 없음 |
| 03:00 Fixture 스케줄 | 유지(enabled, fixture, 다음 2026-11-13 03:00 KST). 이번 작업에서 Staging 변경 없음 |

## 4. 해제에 필요한 최소 조치

1. **출처 승인**(PM·권리 확인)
   - T61 STEP 07 권한 문의를 발송하고 회신을 받거나, PM 이 승인 근거를 갖춰 결정합니다.
   - 그 결과를 SOURCE_REGISTRY 에 `APPROVED` 로 기록합니다. 기록 항목은 승인자, `evidence_ref`, 유효기간, 허용 URL(정규 `GI_Read` 1~5개), 목적 `scheduled_collection`, `max_requests`(robots 포함), 보존기간입니다.
2. **서버 private 정책 파일**: 위 승인 기록을 서버에만 둡니다(저장소 미포함). `dispatcher configure --policy-file` 입력으로 씁니다.
3. **실행 플래그**
   - 서버 private `.env` 에 `CRAWLER_LIVE_SCHEDULE_APPROVED=1` 을 넣습니다.
   - **서버 overlay 에는 현재 이 변수의 전달 줄이 없습니다**(저장소 overlay 에는 있음). 전달 줄을 추가한 뒤 배포로 backend 를 재생성해야 합니다.
4. **1회 실행 경로**
   - 스케줄은 `jobkorea-daily` 한 행뿐입니다. mode 를 live 로 바꾸면 03:00 Fixture 데일리가 Live 로 대체됩니다.
   - 03:00 Fixture 를 유지하면서 1회만 실행하려면, 같은 `eligible()` 게이트를 쓰는 `manual-live` 1회 명령이 필요합니다(작은 코드 PR).
5. **실행 상한**: 요청 수 = robots 1 + 상세 ≤5, 재시도 없음, 403/429/CAPTCHA 즉시 중단. 실행 후 Slack 알림과 DB 검증은 #250 경로를 재사용합니다.

## 5. 후속 위험

- `import_jobkorea_html` 의 Live 모드는 T61 게이트 밖에 있습니다. 운영 컨테이너에서 누구든 실행할 수 있으므로, 같은 승인 게이트를 적용하거나 Staging 이미지에서 Live 옵션을 막는 후속 작업을 권장합니다.
