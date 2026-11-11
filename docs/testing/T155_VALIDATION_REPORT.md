# T155 검증 보고서 — 크롤러 관리자 쓰기·명령 API (잔여 범위)

> 상태: **PARTIAL**. 코드·격리 DB 검증은 끝났고, Staging 적용·실행 검증은 하지 않았습니다(승인 필요).
> `LIVE_COLLECTION=HOLD`. 서버 플래그 `CRAWLER_ADMIN_WRITE_API`는 기본 꺼짐입니다.

## 1. 작업 목적
T155.md 중 아직 구현되지 않은 범위를 채웁니다.
- 검색어 CRUD와 감사 이력 조회
- 설정(스케줄·야간 시간창) 조회·변경
- 수동 실행·중단·재시도 명령. 역할, 멱등 키, 감사 기록, T61 차단 게이트를 적용합니다.
- 401·403·409·422 응답

## 2. 기존 구현·PR 재사용
| 기존 자산 | 재사용 방식 |
|---|---|
| PR #124 `backend/app/routers/crawler_admin.py`(읽기 GET 6개) | **변경 없음.** 같은 `/admin/crawler` 접두사에 쓰기 라우터를 따로 둠 |
| T15 `require_roles("admin")` | 라우터 수준 의존성. 인증·역할 확인이 DB 연결보다 먼저 실행됨 |
| T151 `KeywordStore`(검색어 CRUD + `keyword_audit_events`) | 검색어 쓰기를 모두 위임. 감사 행위자는 `admin:<user_id>`(검증된 세션 기준) |
| T151 `create_job`/`transition` | 실행·재시도는 PENDING 메타데이터 Job만 만듦. 중단은 `PENDING→CANCELLED`만 허용 |
| T61 `check_collection_permission` | `mode=live` 요청은 승인 기록 없이 게이트를 거쳐 항상 거부(`LIVE_NOT_APPROVED:NOT_APPROVED`) |
| T154 `fixture_night_window`(21:00~08:00 KST) | 설정 화면에 읽기 전용으로 노출(`editable: false`) |
| `crawler.storage.staging.connect_configured_database` | 같은 전용 DB 연결 경로. 준비 안 되면 503 |

새로 만든 것:
- `crawler/admin/commands.py`: `CrawlerAdminWriteStore`
- `crawler/storage/migrations/0011_admin_commands.sql`: append-only 명령 원장
- `backend/app/routers/crawler_admin_write.py`

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- HEAD_SHA: PR 댓글에 기록합니다. 커밋 후 SHA가 바뀌므로 이 문서에 넣지 않습니다.

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `crawler/admin/commands.py` | 쓰기 저장소. 검색어 CRUD, 설정, RUN/STOP/RETRY/SCHEDULE_UPDATE, 멱등·원장 |
| `crawler/storage/migrations/0011_admin_commands.sql` | `admin_commands` 표. 런타임 역할 권한은 SELECT·INSERT만(수정·삭제 불가). DB 이름 확인과 롤백 주석 포함 |
| `backend/app/routers/crawler_admin_write.py` | 쓰기 API 11개 경로(아래 §7) |
| `backend/app/core/config.py`, `backend/app/main.py` | `CRAWLER_ADMIN_WRITE_API` 플래그(기본 false)일 때만 라우터 등록 |
| `backend/app/core/env_contract.py`, `.env.example`, `docs/ops/ENVIRONMENT_MATRIX.md` | T111 환경 계약에 새 플래그 등록 |
| `backend/tests/test_t155_crawler_admin_write.py` | TestClient 14건(실제 DB 경로 1건은 선택 실행) |
| `crawler/tests/test_t155_admin_commands.py` | DB 없는 단위 6건(CI `discover`) |
| `crawler/tests/local_t155_admin_write_pg.py` | 격리 PostgreSQL 6건(크롤러 CI 단계에 추가) |
| `.github/workflows/crawler-mvp.yml` | 격리 DB 단계에 0011 적용과 쓰기 테스트 추가. 기존 테스트 뒤에 실행 |

## 5. 선행조건
| 선행 | 상태 |
|---|---|
| T151~T154 | main 병합(Fixture 범위) |
| T15 인증 | main 병합(#48) |
| T155 읽기 API | main 병합(#124) |
| Staging 크롤러 DB에 0011 적용 | **미적용·미승인**. 이 PR은 파일만 추가 |
| 주 Backend 이미지에 `crawler` 패키지 포함 | **미해결**(T155 STEP03 문서와 같음). 없으면 쓰기 API는 503으로 닫힘 |

## 6. 실제 실행 명령
일회용 PostgreSQL 18.6, 127.0.0.1:55496 로컬 클러스터. 크롤러 DB와 역할은 이 클러스터 안에서만 만들었습니다.

```bash
# 크롤러 격리 DB (CI와 같은 역할 구성: 소유자 crawler_student / 런타임 crawler_staging)
psql $OWNER_DSN -f crawler/storage/local_training_schema.sql
for m in crawler/storage/migrations/00*.sql; do psql $OWNER_DSN -v ON_ERROR_STOP=1 -f $m; done   # 0011 두 번 적용 → 재실행 안전
CRAWLER_NIGHT_PG_TEST=1 CRAWLER_NIGHT_TEST_DSN=$RUNTIME_DSN python -m unittest \
  crawler.tests.local_t155_admin_write_pg crawler.tests.local_t155_admin_read_pg -v
python -m unittest discover -s crawler/tests
# Backend (T155 실제 DB 경로 포함)
T155_CRAWLER_PG_DSN=$RUNTIME_DSN python -m pytest -q tests/test_t155_crawler_admin_write.py tests/test_t155_crawler_admin.py \
  tests/test_t111_env_contract.py tests/test_t116_api_compat.py
T16_ISOLATED_DB_TEST=YES ... python -m pytest -q          # 전체 회귀
```

## 7. 정상·오류·권한 검증
API 경로(모두 `/api/v1/admin/crawler` 아래, admin 역할 필요):

| 경로 | 동작 | 응답 |
|---|---|---|
| `POST /keywords` | 생성 + 감사 CREATE | 201 / 409 중복(삭제된 이름 포함) / 422 |
| `PATCH /keywords/{id}` | 이름·우선순위 수정 + 감사 EDIT | 200 / 404 / 409 / 422 |
| `PUT /keywords/{id}/enabled` | 활성·비활성 + 감사 SET_ENABLED | 200 / 404 / 422(문자열 "yes" 거부) |
| `DELETE /keywords/{id}` | 소프트 삭제 + 감사 SOFT_DELETE | 204 / 404 |
| `GET /keywords/{id}/audit` | 감사 이력 | 200 |
| `GET /settings` | 스케줄 메타데이터, 야간 시간창(읽기 전용), `live_collection: HOLD` | 200 |
| `PATCH /schedules/{id}` | `local_time`만 변경. `enabled:true`·`mode:live`는 거부 | 200 / 409 / 422 |
| `POST /commands/run` | Fixture PENDING Job 생성. `live`는 거부 | 201 / 200(재요청) / 409 |
| `POST /commands/stop` | PENDING만 CANCELLED. RUNNING은 Worker 소유라 거부 | 200 / 409 |
| `POST /commands/retry` | FAILED·CANCELLED Job을 새 PENDING Job으로 | 201 / 409 |
| `GET /commands` | 명령 원장(수락·거부 모두) | 200 |

- 명령은 `Idempotency-Key` 헤더가 필수입니다.
- 거부된 명령도 원장에 남고, 409 `CONFLICT`와 함께 `X-Crawler-Command-Id`·`X-Crawler-Command-Reason` 헤더로 사유를 줍니다.
- 오류 코드는 기존 카탈로그만 썼습니다. T116 오류 코드 스냅샷은 변경 없음.

결과:

| 검증 | 결과 | 근거 |
|---|---|---|
| 비로그인 401 (11개 경로) | PASS | 저장소가 열리면 실패하는 의존성으로 확인 |
| 위조 토큰 401 | PASS | 다른 키로 서명한 admin 토큰 |
| 비관리자 403 (11개 경로) | PASS | DB 연결 전 차단 |
| 역할 회수 즉시 403 | PASS | 회수 후 쓰기 0건 |
| 감사 행위자 = 인증 주체 | PASS | 본문 `actor` 필드는 422(extra=forbid) |
| 중복 검색어 409, 입력 422 | PASS | 빈 값·101자·우선순위 0/10000·추가 필드 |
| 멱등: 같은 키 재요청은 같은 Job, 다른 요청은 409 | PASS | TestClient + PG |
| 동시성: 같은 키 4개 연결 동시 요청 → Job 1개 | PASS | PG, advisory xact lock |
| 진행 중 Job이 있으면 실행 거부 | PASS | `ACTIVE_JOB_EXISTS` |
| LIVE 실행·스케줄 live 전환 거부와 원장 기록 | PASS | `LIVE_NOT_APPROVED:NOT_APPROVED` |
| 스케줄 활성화 거부 | PASS | `SCHEDULE_ACTIVATION_REQUIRES_APPROVAL`. 테스트 전후 `enabled/mode/target_urls/approval` 동일 |
| 원장 수정·삭제 불가(런타임 역할) | PASS | `InsufficientPrivilege` |
| 보호 표 행 수 불변 | PASS | postings, raw_artifacts, raw_parse_results, runs, run_events, fixture_* 표 |
| 네트워크 연결 0 | PASS | `socket.create_connection` 차단 상태로 실행 |
| Raw HTML·저장 키·대상 URL·승인 정보 비노출 | PASS | 응답 문자열 검사 |
| 크롤러 DB 없음 → 503 | PASS | 오류 본문에 DB 정보 없음 |
| 플래그 꺼짐 → 쓰기 경로 없음 | PASS | 기존 읽기 테스트의 "keywords에 POST 없음" 그대로 통과 |

## 8. PostgreSQL / Mock / 실제 API 구분
| 구분 | 결과 |
|---|---|
| UNIT_TESTS | PASS. 크롤러 discover 407건(신규 6건 포함, 기존 skip 3건 그대로), T155 Backend 14건 |
| Backend 전체 회귀(Windows 로컬, 격리 PG) | 1654 passed / 1 failed / 31 errors. **main 기준선도 같은 1 failed·31 errors**(문서 저장소 `0700` 권한 검사 등 Windows POSIX 문제)이며, 늘어난 것은 신규 통과 14건뿐입니다. Linux CI 결과는 PR 댓글 |
| POSTGRESQL_TESTS | PASS. 격리 PG 18.6에서 쓰기 6건 + 기존 읽기 3건. CI 크롤러 단계에 같은 테스트를 추가 |
| MOCK_VALIDATION | PASS. 가짜 저장소로 권한·검증·오류 매핑 확인 |
| REAL_API_VALIDATION | PASS(로컬). 실제 T15 인증 + 실제 저장소 + 격리 크롤러 DB를 TestClient HTTP로 확인(`test_real_store_through_http`). Staging 아님 |
| STAGING_VALIDATION | NOT_RUN. 0011 미적용, 플래그 꺼짐 |
| LIVE_COLLECTION | HOLD |

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
1. Staging 크롤러 DB에 0011을 적용하려면 별도 승인이 필요합니다(백업 → 적용 → 확인).
2. 주 Backend 이미지에 `crawler` 패키지와 전용 DB 권한이 없습니다(T155 STEP03과 같은 문제). 그 전에는 플래그를 켜도 503입니다.
3. 수동 실행은 PENDING 메타데이터만 만듭니다. 이 Job을 실제로 처리하는 경로(Fixture payload 연결, 야간 실행기)는 기존 T154 도구의 수동 실행에 맡겼고, API에서 Worker를 띄우지 않습니다.
4. 같은 이름 검색어를 삭제 후 다시 만들면 409입니다. 기존 0003의 `normalized_keyword UNIQUE`(삭제 행 포함) 때문이며, 복원 기능은 PM 결정이 필요합니다.
5. 런타임 역할은 DELETE 권한이 없어서 CI 크롤러 DB에 합성 메타데이터가 남습니다(일회용 DB라 영향 없음).

## 11. 후속 작업
- T156 관리자 UI가 이 API를 씁니다(Stacked PR).
- Staging 적용 계획: 0011 수동 적용 → Backend 이미지 통합 → 격리 401/403/200/409/422/503 → Fixture E2E 순서. 모두 승인 후.
- Redmine #1582에 이 보고서를 연결합니다(직접 갱신 안 함).
