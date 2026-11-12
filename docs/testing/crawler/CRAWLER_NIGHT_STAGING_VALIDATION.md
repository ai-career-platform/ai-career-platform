# 야간 크롤러 Staging 준비 검증 (CRAWLER_NIGHT_03)

> 2026-11-12 19:51~19:55 KST · 판정: **PARTIAL**
> - 끝난 것
>   - Staging 배포 확인
>   - 0012 적용·검증
>   - 키워드 보완
>   - 야간 기본 OFF·03:00 Fixture·기존 데이터 보존 확인
> - 남은 것
>   - #254 (e43daeb 재제출) 리뷰·병합
>   - Live 수집 BLOCKED (T61 승인 HOLD)
>
> 증빙: `evidence/night03/*.txt` (호스트 주소·비밀값 없음). 모든 조회는 읽기 전용 세션이며, 변경은 아래 §3·§5 두 가지뿐입니다.

## 1. 배포 (STEP 01)

| 항목 | 결과 |
|---|---|
| main | `b1e6ad720fa33ee1ff313c1eee34ae9a7a67f588` (#253) |
| Staging `/api/version` | 같은 SHA |
| Auto-CD | main CI·Crawler MVP success → 게시 run `43202461281` success → deploy 서비스 `deploy-start` 10:43:05Z → `deploy-end` 10:44:20Z, Result=success |
| 컨테이너 | backend·frontend·db healthy. backend 이미지는 게시 digest(`…04e51ee8418b…`) |
| API | `/api/health`, `/api/health/db`, `/api/v1/job-postings`, `/api/jobs/collected`, `/`, `/staging-status.html` 모두 200 |
| 타이머 | Auto-CD enabled/active, 크롤러 디스패처 enabled/active |
| 새 코드 | backend 에 `crawler.jobs.night_crawl` 있음 |

- #253 은 승인 리뷰 0건 상태에서 저장소 bypass 권한 계정으로 병합되었습니다(이 작업이 병합하지 않음).

## 2. 야간 기본 OFF·Fixture·Slack (STEP 03)

| 항목 | 결과 |
|---|---|
| `CRAWLER_NIGHT_ENABLED` | 미설정 → 코드 기본 OFF |
| `CRAWLER_LIVE_SCHEDULE_APPROVED` | 미설정 |
| 서버 overlay | 위 두 변수의 전달 줄 없음(저장소 overlay 에는 있음). 서버 `.env` 에도 없음 |
| 디스패처 결과 | 0012 적용·키워드 등록 뒤 첫 poll(10:55:26Z): `{"status":"IDLE","external_requests":0,"night":{"night":"DISABLED"}}` |
| 03:00 Fixture | `jobkorea-daily` enabled=true, fixture, Asia/Seoul, 03:00, 다음 2026-11-13 03:00 KST, 대상 URL 0 |
| Slack | `configured=true`, `SLACK_WEBHOOK_URL`, 충돌 없음 |
| Live HTTP | 0 (마지막 live 공고 저장 11-08 09:50 그대로) |

## 3. 마이그레이션 0012 (STEP 02)

**적용 전 확인**
- 대상 DB: 크롤러 전용 `ai_career_crawler_training`, 스키마 `crawler_training`. 서비스 DB 가 아닙니다.
- 실행 주체: DB 소유자 `<db-owner-role>`(T151 이후 테이블의 owner). 0002 계열 테이블의 owner 는 `crawler_staging` 입니다.
- 마이그레이션 원장 테이블은 없습니다. 기존과 같이 런북 절차로 `psql` 을 수동 적용했습니다.
- 0012 미적용(`night_job_results`·`night_summaries` 없음). 선행 조건 0003·0007 은 충족했습니다.
  - 참고: 0011(`admin_commands`)은 Staging 에 적용되어 있지 않습니다. 이번 범위 밖입니다.
- SQL 검사(sha256 앞 16자 `2a265a984ddcab9d`)
  - 실행문은 `CREATE TABLE/INDEX IF NOT EXISTS` 4개, `GRANT` 2개, 대상 DB 확인 블록뿐입니다.
  - DROP·TRUNCATE·DELETE·ALTER·데이터 변경은 없습니다.

**백업** (RELEASE_RUNBOOK 백업 절차)
- 명령: `pg_dump -Fc --no-owner --no-privileges`
- 파일: 서버 `backups/crawler_training_pre0012_20261112105303.dump`, 51,943 bytes, mode 600, sha256 앞 16자 `34a544174c8c1b1b`
- `pg_restore --list` 결과 80 항목

**적용**: 2026-11-12 19:53 KST, `psql -v ON_ERROR_STOP=1`, 1회, 단일 트랜잭션. 출력 `BEGIN … CREATE TABLE … CREATE INDEX ×2 … CREATE TABLE … COMMIT`, exit 0.

**적용 후**

| 항목 | 전 | 후 |
|---|---|---|
| crawler_training 테이블 | 14 | 16 (+`night_job_results`, `night_summaries`) |
| 공고 | 35 (2/28/5) | 35 (2/28/5) |
| runs / run_events | 2 / 8 | 2 / 8 |
| keyword_jobs / discoveries / checkpoints | 14 / 28 / 2 | 14 / 28 / 2 |
| 서비스 DB | 테이블 329, 스키마 md5 `b2d28503651df45de540bab394de13d5` | 같음 |

- 제약조건
  - CHECK: attempt, outcome, mode, error_code, 각 건수 ≥0, RUNNING↔ended_at
  - FK: job_id, keyword_id
  - PK·UNIQUE(night_date, keyword_id, attempt)
  - NOT NULL
- 인덱스: `night_job_results_pkey`, `night_job_results_night_idx`, `night_job_results_one_running`(RUNNING 1건 제한), UNIQUE 키, `night_summaries_pkey`
- 권한: `crawler_staging` 에 두 테이블 SELECT/INSERT/UPDATE. DELETE 없음
- 두 테이블 모두 0행
- 롤백: 두 테이블이 비어 있는 동안은 0012 파일 하단 주석의 DROP 2개를 쓰거나, 위 백업에서 복원합니다.

## 4. 키워드 (STEP 04)

**적용 전**: 6개 중 `데이터 분석`(id 3), `AI 엔지니어`(id 6)만 있었습니다.

**보완**
- 기존 `KeywordStore.add_keyword` 로 4개를 추가했습니다: AX(37), 빅데이터(38), 머신러닝(39), 딥러닝(40).
- 실행 역할은 `crawler_staging`, actor 는 `system:crawler_night_03` 입니다. 감사 기록 CREATE 4건이 남았습니다.
- 등록 전 확인
  - 활성 키워드를 읽는 코드는 야간 실행기뿐이고, 이 실행기는 `CRAWLER_NIGHT_ENABLED` 가 꺼져 있으면 아무것도 하지 않습니다.
  - 그래서 키워드 등록만으로는 작업이 시작되지 않습니다. 등록 뒤 poll 이 `night: DISABLED` 임을 확인했습니다.

| 키워드 | id | 활성 | 작업 | 체크포인트 |
|---|---|---|---|---|
| 데이터 분석 | 3 | 예 | 0 | 없음 |
| AI 엔지니어 | 6 | 예 | 0 | 없음 |
| AX | 37 | 예 | 0 | 없음 |
| 빅데이터 | 38 | 예 | 0 | 없음 |
| 머신러닝 | 39 | 예 | 0 | 없음 |
| 딥러닝 | 40 | 예 | 0 | 없음 |

- 정규화 기준 중복 0건. 전체 키워드 12개(기존 6개 + 합성 2개 + 신규 4개), 모두 활성입니다.

## 5. 후속 커밋 e43daeb (STEP 05)

| 항목 | 결과 |
|---|---|
| 존재 | 있음. `origin/feat/crawler-night-keyword-jobs` 의 HEAD |
| main 포함 | **아니오** |
| 원인 | push 는 10:40:49Z 에 원격 반영됐지만, GitHub 가 PR #253 head 를 갱신하기 전(head `0d64b03`)에 병합되었습니다 |
| 차이 | `0d64b03` 과 main `b1e6ad7` 의 트리가 같습니다. 따라서 `e43daeb` 의 diff(11 파일) 전체가 미병합분이고 중복이 없습니다 |
| 목적 | 모든 Live HTTP 를 `fetch_pages()` 의 T61 게이트로 통일(#85 CLI 우회 경로 차단) |
| 처리 | main 에서 `fix/crawler-live-http-t61-gate` 생성 → `git cherry-pick -x e43daeb`(트리 동일) → **PR #254**. crawler 단위 테스트 전체 OK, Crasnec 리뷰 요청 |

## 6. 최종 안전성 (STEP 06, 19:54~19:55 KST)

- backend·frontend·db healthy, API 6종 200
- 공고 35 보존, runs 2·events 8 보존
- 03:00 Fixture 스케줄 정상, 디스패처·Auto-CD 타이머 정상
- Slack 설정 유지
- 야간 Live 기본 OFF, Live HTTP 0
- Production 과 서비스 DB 는 변경 없음

## 7. Live 차단과 후속 작업

- Live 수집은 **BLOCKED** 입니다. 이유는 두 가지입니다.
  - T61 JobKorea 출처 승인이 HOLD 입니다.
  - 현재 T61 은 명시된 `GI_Read` URL 만 허용하므로 키워드 검색 URL 이 범위 밖입니다.
- 후속 작업
  1. #254 독립 리뷰·병합 → Auto-CD
  2. [PM/T61] 출처 승인, 검색 페이지 범위 결정(evaluator 확장은 별도 PR)
  3. [서버] 승인 파일 마운트, overlay 에 `CRAWLER_NIGHT_ENABLED`·`CRAWLER_LIVE_SCHEDULE_APPROVED`·`CRAWLER_NIGHT_POLICY_FILE` 전달 줄 추가
  4. 제한 Live 1회 → 첫 야간 관찰 → Slack 종합 확인
  5. (별건) Staging 0011 미적용 상태 정리 여부 결정
