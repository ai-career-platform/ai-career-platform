# 실제 수집 1회 검증 — DB·Slack·보존 확인 (CRAWLER_NIGHT_08)

> Live 수집이 BLOCKED 되어 실행하지 않았습니다([결과](CRAWLER_NIGHT_08_LIVE_COLLECTION_RESULT.md)).
> 이 문서는 실행 전 기준선과 보존 상태를 기록합니다. Staging 쓰기는 0 건입니다. DB 조회는 `default_transaction_read_only=on` 세션에서 했습니다.

## 1. 실행 전후 DB 비교 (`ai_career_crawler_training`)

| 항목 | 기준선 2026-11-12 21:56 KST | 이후 21:57 KST | 변화 |
|---|---|---|---|
| postings `jobkorea` (fixture) | 2 | 2 | 없음 |
| postings `jobkorea_imported` | 28 | 28 | 없음 |
| postings `jobkorea_live` | 5 (마지막 갱신 2026-11-08) | 5 | 없음 |
| runs | 2 (fixture SUCCEEDED 2) | 2 | 없음 |
| run_events | 8 | 8 | 없음 |
| night_job_results | 0 | 0 | 없음 |
| keyword_jobs | 14 (마지막 2026-11-08) | 14 | 없음 |
| keyword_checkpoints | 2 (마지막 2026-11-08) | 2 | 없음 |

- Live 공고 5건은 2026-11-08 에 저장된 기존 데이터입니다. 이번 단계의 수집 결과가 아닙니다.
- 실행 이력·체크포인트·키워드 연결은 기록할 실행이 없어 **검증하지 못했습니다(NOT_RUN)**.

## 2. Slack

| 항목 | 값 |
|---|---|
| Webhook 설정 | backend 에 SET (값은 기록하지 않음) |
| 이번 단계 전송 | 없음. 실행이 없으므로 알림도 없음 |
| SLACK_HTTP_STATUS | N/A |
| SLACK_DELIVERY | NOT_RUN |

- CRAWLER_NIGHT_07 의 `[STAGING E2E TEST] run=e2e-5abde009` 메시지는 테스트 sender 가 가로챈 것입니다(MOCK_VERIFIED). 실제 채널 전송도, 실제 Live 결과도 아닙니다.

## 3. 기존 운영 상태 보존

| 항목 | 상태 |
|---|---|
| 03:00 Fixture 스케줄 | `jobkorea-daily` enabled / fixture / 03:00, next_run 2026-11-13 03:00 KST (변화 없음) |
| Dispatcher Timer | enabled / active, 5분 간격. 21:00 이후 결과는 모두 `IDLE`, `night=DISABLED`, `external_requests=0` |
| 야간 자동 Live | OFF (`CRAWLER_NIGHT_ENABLED` UNSET) |
| 컨테이너 | backend·frontend·db healthy |
| Auto-CD | deploy timer 정상, `d5dd380` UNCHANGED |
| 다른 크롤러 프로세스 | 0 |
| Production | 변경 없음 |

## 4. 남은 문제

1. **T61 범위**: 게이트가 GI_Read 상세 URL 만 받으므로 키워드 검색 기반 수집은 승인 파일로 풀 수 없습니다. 게이트 코드 변경과 T61 결정이 필요합니다.
2. **운영 설정**: 승인 후에도 서버 `.env` 와 직접 관리하는 overlay 에 `CRAWLER_LIVE_SCHEDULE_APPROVED`·`CRAWLER_NIGHT_POLICY_FILE` 전달을 추가해야 합니다. overlay 는 git 에서 동기화되지 않습니다.
3. **서버 `automation/deploy.py`**: 2026-11-06 판으로 main 과 해시가 다릅니다. F-07 수정이 적용되지 않았습니다.
4. **Staging `/api/version` 없음(404)**: 배포 SHA 는 Auto-CD 로그로만 확인할 수 있습니다.
5. **backend 환경변수 이름 오타 `SLACK_WEBHOOK_RUL`**: 동작에 영향은 없지만 정리가 필요합니다.
