# T99 — 채용공고 복합 검색·인덱스 최적화

> 상태: **PARTIAL** — 구현·격리 DB 검증 완료. 운영 활성화와 인덱스 적용은 **HOLD**(T98 계약 승인 전, 기능 플래그 기본 꺼짐).
> 기준: [T98 계약](T98_ADVANCED_SEARCH_CONTRACT.md)(PROPOSED, PR #201) — 이 브랜치는 T98 브랜치 위에 쌓여 있습니다(T98 먼저 병합).
> main `ceee31d` · 2026-11-11 · F-012 · FR-JOB-005 · 선행: T18 병합, T63(합성만), T98(미병합)

## 1. 무엇을 바꿨나

| 파일 | 변경 |
|---|---|
| `backend/app/services/job_search.py` | 신규. 지역 별칭 표(T98 §4), 게시 기간, 검색어 정규화(공백 정리·1~100자), 다중 값 개수 상한(중복 제거 **전**) |
| `backend/app/routers/job_postings.py` | 목록 경로를 `legacy_list_router`(T18 그대로)와 `advanced_list_router`(T98)로 나눔 |
| `backend/app/main.py`, `app/core/config.py` | `JOB_SEARCH_ADVANCED=true`일 때만 고급 라우터 등록. **기본 꺼짐** — 꺼지면 OpenAPI·동작이 T18과 같음 |
| `backend/app/repositories/job_postings.py` | `PostingFilter`에 기본값 있는 필드 추가(기존 호출부 무변경), 제목·기업명 OR, IN 목록, 지역 첫 단어 판정식, 게시 기간. 무한대를 SQL 상수로 바꿈(§4 원인 1) |
| `backend/app/services/job_postings.py` | 고급 조건을 정규화해 cursor에 묶음(`v=adv1`) — 순서·중복만 다른 같은 조건은 같은 cursor |
| `backend/app/schemas/job_postings.py` | `RegionCode`, `PostedWithin` |
| `backend/tests/security/security_inventory.py` | 목록 경로가 `create_app`에서 붙으므로 인벤토리 원천에 추가(경로·분류 변화 없음) |
| `database/proposed/T99_job_search_indexes.sql` | 인덱스 **제안**(migration 아님). 권장 1개 + 비권장 2개(측정 근거) |
| `database/proposed/T99_job_search_trgm_option.sql` | `pg_trgm` 옵션 — **비권장**(§4) |
| `backend/perf/t99_search_bench.py` | 10만 건 격리 DB 측정 스크립트(T88 가드 재사용) |
| 시험 | `tests/test_t99_job_search.py`(단위 15), `tests/test_t99_job_search_postgres.py`(PG 14) |

## 2. 계약 대비 구현

| T98 항목 | 구현 | 확인 |
|---|---|---|
| q 제목·기업명, 공백 정리, `%`·`_`·`\` 문자 그대로 | `ILIKE ... ESCAPE '\'` 바인딩 | A02~A05, 주입 문자열 6종 |
| 다중 값 OR / 조건 AND / NULL 제외 | `IN (...)`, 지역은 별칭 접두어 OR | A06~A12 |
| 지역 첫 단어 판정 | `split_part(regexp_replace(btrim(location_text), '\s+', ' ', 'g'), ' ', 1) LIKE '별칭%'` | A08~A10, 탭·앞뒤 공백, "재택근무" 제외 |
| 게시 기간 | `published_at >= now - 기간` (요청 시각) | A11, A15 |
| 안정 정렬·NULL 위치 | T18 keyset 그대로 | A01(동률), A13 |
| 검증 422 | FastAPI 열거형 + 정규화 함수 | E01~E09 |
| cursor 조건 묶음 | 정규화 dict digest | 순서·중복 다름 → 허용, 필터·정렬 다름 → 400 |
| 기준 시점 | 각 요청 시각 | 페이지 사이 마감 → 다음 페이지에서 빠지고 중복 없음 |

## 3. 시험 결과 (로컬: Windows 11 · Python 3.12 · PostgreSQL 18.6 일회용 클러스터)

| 시험 | 결과 |
|---|---|
| T98 수용 사례 16건을 **실제 SQL·HTTP**로 | PASS (기대값 = T98 JSON, 손으로 작성) |
| 거부 9건 → 422 `VALIDATION_FAILED` | PASS |
| 페이지 크기 1·2·3으로 끝까지 → 한 번에 받은 결과와 같음(동률 포함) | PASS |
| cursor 조건 묶음, 주입·이스케이프 문자열 6종(표 손상 없음), 지역 공백 처리, 페이지 사이 마감 | PASS |
| 플래그 꺼짐: 기업명 검색 안 됨(T18), 모르는 매개변수 무시, OpenAPI 매개변수 7개 그대로 | PASS |
| 플래그 켜짐: OpenAPI 매개변수 10개, 제안 인덱스 적용 후에도 결과 동일 | PASS |
| 단위: 지역 표·열거형 = T98 문서, 정규화·상한, 플래그 기본 꺼짐(`true`만 켬), 목록 경로 정확히 1개 | PASS |
| 전체 백엔드 | **1224 passed, 95 skipped**, 실패·오류 32건 = 기존 Windows 전용 문서 저장소 시험(`test_documents.py`, `security/test_security_upload.py`), PASS로 세지 않음 |

## 4. 성능·실행 계획 (격리 DB, 합성 10만 건)

조건: 공고 100,000건(게시 88,464 · 마감 9,826 · 작성 중 1,710), 기업 2,000, 열마다 독립 해시 분포, 페이지 21행(20+다음 확인), 시나리오별 30회(예열 3회), 저장소 수준(HTTP 제외), 단일 연결. 원자료: [`T99_SEARCH_PERF_RESULTS.json`](T99_SEARCH_PERF_RESULTS.json).

| 시나리오 | (A) 0001 인덱스만 p95 | (B) + 제안 인덱스 p95 | 사용 인덱스(B) |
|---|---|---|---|
| S01 기본 첫 페이지 | 1.2 ms | 1.8 ms | ix_job_postings_3 |
| S02 q 흔한 단어 | 1.3 | 1.6 | ix_job_postings_3 |
| S03 q 드문 단어(기업명) | 21.8 | 21.8 | 없음(공고·기업 Seq Scan) |
| S04 고용형태 | 1.5 | 1.1 | t99_employment |
| S05 지역 서울+경기 | 1.3 | 1.4 | ix_job_postings_3 |
| S06 지역 제주(드묾) | 1.5 | 5.4 | t99_region |
| S07 7일 + 정규직 | 1.3 | 1.2 | t99_employment |
| S08 q+고용형태+지역+7일 | 2.8 | 4.6 | t99_region |
| **S09 마감 임박순(게시 중)** | **24.6** | **19.6** | **t99_expires** |
| **S10 마감 포함 + 마감 임박순** | **124.5** | **1.6** | **t99_expires** |
| S11 기업 3곳 | 1.6 | 1.3 | ix_job_postings_1 |
| S12 깊은 페이지(2,000행 뒤) | 1.7 | 1.5 | ix_job_postings_3 |

- 제안 목표(T98 §7, p95 < 150 ms)는 (A)·(B) 모두 충족합니다. 다만 (A)의 S10은 124 ms로 여유가 거의 없습니다.
- **원인 1(코드 수정)**: 무한대를 `CAST(:param AS timestamptz)`로 보내면, text→timestamptz 캐스트가 STABLE이라 상수로 접히지 않아 식 인덱스와 맞지 않습니다. `'infinity'::timestamptz` SQL 상수로 바꿨습니다(의미 동일, T18 시험 통과).
- **원인 2(인덱스 조건)**: 마감 포함 목록은 `status IN ('published','closed')`라서 `status='published'` 부분 인덱스를 못 씁니다. 조건을 넓혔습니다.
- **권장**: `ix_job_postings_t99_expires` 하나. 고용형태·지역 인덱스는 10만 건에서 이득이 없거나(S04·S07 ±0.4 ms) 오히려 나빠져(S06) 비권장입니다. 데이터가 커지면 다시 측정합니다.
- **pg_trgm 비권장**: (C) 단계에서도 S03이 개선되지 않았습니다. 측정 클러스터는 C 로케일이라 한글 trigram이 만들어지지 않습니다. 제목·기업명 OR이 두 표에 걸쳐 있어 단일 GIN으로 풀리지도 않습니다. Staging 로케일·확장 권한은 확인하지 않았습니다(T98 D-5).
- **한계**: 로컬 Windows 단일 연결 측정이며 HTTP·동시성은 포함하지 않았습니다(T88 기준선 참고). 실제 잡코리아 데이터 분포가 아닙니다.

```powershell
cd backend
$env:T16_ISOLATED_DB_TEST="YES"; $env:T16_TEST_ADMIN_URL="postgresql://<admin>@127.0.0.1:<port>/t16_profile_test"
python -m pytest -q tests/test_t99_job_search.py tests/test_t99_job_search_postgres.py
python -m perf.t99_search_bench --postings 100000 --out ../docs/search/T99_SEARCH_PERF_RESULTS.json
```

## 5. HOLD / 결정 필요

| 항목 | 상태 | 필요한 것 |
|---|---|---|
| `JOB_SEARCH_ADVANCED` 운영·Staging 활성화 | HOLD | T98 계약 승인(D-1~D-6) |
| `docs/api/openapi.yaml` 반영 + 프런트 타입 생성 | HOLD | 계약 승인 후(지금은 플래그 꺼짐 = 기존 계약과 일치) |
| 인덱스 적용(`ix_job_postings_t99_expires`) | HOLD | 정식 migration 번호 + 운영은 `CREATE INDEX CONCURRENTLY` 절차(러너가 CONCURRENTLY 금지) — PM·DB 결정 |
| 실제 `location_text` 분포로 지역 규칙 검증 | HOLD | 수집 승인(T61) 후 |
| 기술·경력 필터 | HOLD | T98 §2 |
