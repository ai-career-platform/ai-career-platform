# T152 검증 보고서 — Raw 원본 고아 파일 탐지·보존 기한 계획 (누락분 보완)

> T152(목록·상세 HTML 원본 보관)의 기본 기능은 이미 main에 있습니다(#98·#99·#100, 문길래).
> - 이 PR은 **중복 개발 없이** 작업지시서 T152.md 2-4항 중 빠진 부분만 보완합니다.
> - 빠진 부분은 "보존기한·삭제·실패 시 고아 파일 복구 설계"입니다.
> - 기존 저장소 코드(`raw_artifact_store.py`)와 migration 은 바꾸지 않았습니다.

## 1. 작업 목적
파일 쓰기와 DB INSERT 는 하나의 트랜잭션이 아닙니다(STEP01 문서). 그래서 실패하면 고아 파일이 생길 수 있는데, 지금까지는 "자동 삭제 금지, 수동 검사"라는 원칙만 있고 검사 도구가 없었습니다. 이번에 **읽기 전용** 대조 도구와 보존 기한 **검토 계획(dry-run)** 을 추가합니다.

## 2. 기존 구현·PR 재사용
| 기존 | 상태 | 이번 처리 |
|---|---|---|
| 크기 제한(2 MB)·Content-Type·해시 이름·중복(내용 주소)·0700/0600·symlink 거부·`read_verified` | main(#98) | 재사용(변경 없음) |
| 키워드 교차 PK 수정 | main(#99) | 재사용 |
| 목록→상세 배치 | main(#100) | 재사용 |
| 0005 `raw_artifacts`, 0006 `raw_parse_results`(lineage) | main | 읽기만 |
| **고아 파일 탐지** | 없음 | `reconcile()` 추가 |
| **보존 기한·삭제** | 없음 | `retention_plan()` 추가. 검토용이며 **삭제 기능은 만들지 않음** |

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16` (main), 독립 PR
- HEAD_SHA: PR 댓글

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `crawler/jobs/raw_artifact_audit.py` | `reconcile()`, `retention_plan()`, `load_rows()`(READ ONLY 트랜잭션), CLI |
| `crawler/tests/test_t152_raw_artifact_audit.py` | 오프라인 10건 |
| `crawler/tests/local_t152_artifact_audit_pg.py` | 격리 PostgreSQL 2건(opt-in `CRAWLER_NIGHT_PG_TEST=1`) |
| `.github/workflows/crawler-mvp.yml` | 기존 PG 단계에 위 시험 한 줄 추가(T155 읽기 시험 다음) |
| `docs/testing/T152_VALIDATION_REPORT.md` | 이 보고서 |

## 5. 선행조건
T151·T61·T62는 병합되어 있습니다(Fixture 범위). 실제 사이트 수집은 HOLD 입니다.

## 6. 실제 실행 명령
```bash
python -m unittest discover -s crawler/tests                         # 오프라인 전체
# 격리 PG(CI와 같은 순서): local_training_schema.sql → 0002..0010 → crawler_staging 으로 실행
CRAWLER_NIGHT_PG_TEST=1 CRAWLER_NIGHT_TEST_DSN=postgresql://crawler_staging@127.0.0.1:<port>/ai_career_crawler_training \
  python -m unittest crawler.tests.local_t155_admin_read_pg crawler.tests.local_t152_artifact_audit_pg -v
# 운영자용(읽기 전용, DSN 은 환경변수 이름만 받음·출력 안 함)
CRAWLER_LOCAL_DATABASE_URL=... python -m crawler.jobs.raw_artifact_audit --root <raw dir> --keep-days 30
```

## 7. 정상·오류·권한 검증
| 항목 | 결과 |
|---|---|
| 깨끗한 저장소(같은 내용을 두 키워드가 공유) → clean, 파일 2·행 3·키 2 | PASS |
| 고아 파일(행 없음), 행만 있고 파일 없음, 해시 불일치(변조), 크기 불일치, 잘못된 storage_key 행(`../../etc/passwd`), `.tmp-*` 중단 잔여물, 예상 밖 파일 → 각각 정확히 보고 | PASS |
| **아무것도 지우지 않음**(검사 전후 파일 목록·크기 동일) | PASS |
| 보고서에 HTML 본문·URL 없음 | PASS |
| 크기만 검사 모드(`--no-hash`)와 기본 재해시 차이 | PASS |
| 없는 root 거부 | PASS |
| 보존 계획: 오래되고 쓰이지 않음 → 검토 대상 / lineage 가 참조 → 보류 / 같은 내용이 최근 다시 수집됨 → 보류 / 경계(정확히 cut-off) 유지 / keep_days 범위·시간대 없는 now 거부 | PASS |
| CLI: DSN 환경변수가 없으면 종료(DSN 값은 출력하지 않음) | PASS |
| POSIX 권한(파일 0600 초과) 보고 | **Windows SKIP**, Linux CI에서 실행 |
| symlink 항목 보고 | **Windows SKIP**(권한 없음), Linux CI에서 실행 |
| [PG] 실제 0005·0006 메타데이터 + crawler_staging: 고아 탐지, 다른 시험의 행은 "missing"으로만 보고(수정 안 함), 표 4개 행 수 변화 없음 | PASS(로컬 PG 18.6) |
| [PG] `load_rows` 의 READ ONLY 트랜잭션에서 UPDATE 거부(`ReadOnlySqlTransaction`) | PASS |

## 8. PostgreSQL / Mock / 실제 API 구분
- 오프라인: 임시 디렉터리 + 합성 바이트
- PostgreSQL
  - 로컬: 일회용 PG 18.6 전용 클러스터에서 CI와 같은 역할·migration 순서로 실행했습니다(공유 DB 아님).
  - CI: GitHub Actions 일회용 서비스에서 실행합니다.
- 실제 사이트·Staging: **실행 안 함**. Live 수집은 HOLD 이고 Staging 원본 디렉터리 점검은 승인이 필요합니다.

크롤러 오프라인 전체(Windows): **411 OK, skipped 5**. main 은 401 OK, skipped 3 이므로 이번 PR 에서 +10 건, Windows skip +2 건입니다.

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- 보존 기한(keep_days)과 삭제 절차 승인(PM). 현재 기본 30일은 **검토용 가정**입니다.
- Staging 원본 디렉터리에 대한 실제 점검은 접속 승인 후에 가능합니다(읽기 전용).
- 실제 삭제 기능은 의도적으로 만들지 않았습니다. 승인 후 별도 PR 로, 백업과 감사 기록을 포함해 만들어야 합니다.

## 11. 후속 작업
- 승인되면 Staging 점검 → 결과 JSON 을 증빙으로 보관
- 삭제 작업(승인 필요): lineage 보류·공유 파일 규칙을 그대로 쓰고, 삭제 전 백업, 감사 행 기록
- T155 관리자 API 에 점검 결과(개수만) 조회를 넣을지 검토

```text
UNIT_TESTS=PASS
POSTGRESQL_TESTS=PASS (local disposable PG 18.6; CI service on push)
FRONTEND_TESTS=NOT_RUN
BROWSER_E2E=NOT_RUN
MOCK_VALIDATION=PASS
REAL_API_VALIDATION=NOT_RUN
STAGING_VALIDATION=NOT_RUN
LIVE_COLLECTION=HOLD
```
