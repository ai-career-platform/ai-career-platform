# 채용시장 지표 (T65 계약 · T66 집계)

계약(정의·단위·구간·빈 구간·시점 누수): [docs/data/MARKET_METRICS_CONTRACT.md](../../docs/data/MARKET_METRICS_CONTRACT.md)

| 파일 | 역할 |
|---|---|
| `reference_metrics.sql` | T65 기준 계산 SQL (읽기 전용). 집계 job이 쓰는 `backend/app/sql/market_reference_metrics.sql`과 **같은 내용**이어야 한다 (테스트로 강제) |
| `verify_observations.sql` | T66 검산 SQL. 적재된 행을 원천 공고에서 다른 방식으로 다시 세어 불일치만 출력한다. **0행 = PASS** |
| `t65_fixture.sql` / `t65_expected.json` | 합성 공고 fixture와 손 계산 정답 (경계 사례 E1~E10) |

## 집계 job (T66)

```powershell
cd backend
# 계산만 (쓰기 없음)
.\.venv\Scripts\python.exe -m app.market_aggregation --source t65_fixture --period week --as-of 2026-11-10T09:00:00+09:00 --dry-run
# 처음 적재: 과거 구간까지 채우기
.\.venv\Scripts\python.exe -m app.market_aggregation --source t65_fixture --period week --as-of 2026-11-10T09:00:00+09:00 --backfill-from 2026-10-05
# 정기 실행: 최근 2개 완료 구간만 다시 계산 (as_of 생략 = 지금)
.\.venv\Scripts\python.exe -m app.market_aggregation --source t65_fixture --period week
```

출력 예: `MARKET_AGGREGATION=APPLIED source=t65_fixture period=week range=[2026-10-05,2026-11-09) as_of=2026-11-10T09:00:00+09:00 deleted=0 inserted=20`

| 동작 | 규칙 |
|---|---|
| 재계산 창 | `as_of`가 속한 진행 중 구간 **직전까지** 최근 `--lookback`개(기본 2). 더 오래된 구간은 고정 |
| 적재 방식 | 창 안의 (출처, 기간 종류) 행을 지우고 같은 트랜잭션에서 다시 넣는다. 실패하면 전부 롤백 |
| 중복 | 재실행해도 중복 0. 이미 있던 전체 시장(NULL 직무) 중복 행도 창 안이면 정리된다 |
| 동시 실행 | 같은 출처·기간 종류는 `pg_advisory_xact_lock`으로 하나씩 실행 |
| 늦게 들어온 공고 | 창 안이면 다음 실행에 반영된다. 창 밖이면 고정 값이 유지되고, 검산 SQL이 차이를 보고하면 운영자가 `--backfill-from`으로 다시 계산한다 |
| 게시 취소(draft로 되돌림)·삭제 | 창 안이면 다음 실행에서 빠진다. 마감(`closed`)은 게시 이력이므로 계속 센다 (계약 §3.1) |
| 안전장치 | 쓰기는 `APP_ENV=local-dev/test`를 명시하고 DB 호스트가 loopback일 때만 가능. 미설정 및 공유 환경은 `--approval` 문자열 유무와 관계없이 거부. Staging 적재는 별도 운영 절차 필요 (`--dry-run`은 가능) |
| 로그 | 출처 코드·구간·건수만 남긴다. 공고 내용·URL·DB 접속 정보는 출력하지 않는다 |

## 검산

적재에 쓴 것과 같은 `as_of`·구간으로 `verify_observations.sql`을 실행한다. 바인드 매개변수는 파일 머리말에 있다.

| check_name | 뜻 |
|---|---|
| `duplicate_key` | 같은 키가 두 번 이상 저장됨 (NULL 직무 포함) |
| `posting_count_mismatch` | 저장된 공고 수 ≠ 원천 공고 수 |
| `skill_share_mismatch` | 저장된 기술 비율 ≠ 원천 계산, 또는 표본 5건 미만인데 저장됨 |
| `missing_bucket` | 공고 수 행이 누락됨 (직무별 및 성공 수집 0건 구간 포함) |
| `missing_skill_share` | 표본 조건을 충족하는 기술별 비율 행이 누락됨 |

## 테스트

```powershell
cd backend
$env:T15_TEST_DATABASE_URL = "postgresql://postgres:<임의값>@127.0.0.1:55433/postgres"   # 일회용 DB만
.\.venv\Scripts\python.exe -m pytest -q tests/test_t65_market_metrics_postgres.py tests/test_t66_market_aggregation.py tests/test_t66_market_aggregation_postgres.py
```

## Staging·스케줄 (승인 전 HOLD)

- 이 job은 **스케줄에 등록하지 않았다.** Staging·운영 정기 실행(systemd timer 등)은 작업지시서 §5에 따라 PM 승인 후 별도로 한다.
- Staging에 적용하려면 먼저 migration 0003이 적용돼 있어야 한다 ([migrations/README.md](../migrations/README.md) §5).
- 실제 잡코리아 공고는 T61 게이트에 따라 수집 HOLD 상태라, 지금 Staging에 돌려도 집계할 원천이 없다.
