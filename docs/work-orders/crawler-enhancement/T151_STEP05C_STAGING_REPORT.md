# T151 STEP 05C — 스테이징 Migration/메타데이터 Smoke 결과

> Feature #1578, T151 · 코드/스테이징 SHA `b546eee1b954170a6faf3344fc45c4b4e1b09f9b` · **사용자 제공 Codex 보고**. 로컬 Evidence 파일 원문은 GitHub 코디네이터가 직접 열람하지 못함.

## 결과
- `0003_keywords_jobs.sql`: PASS
- `0004_keyword_audit.sql`: PASS
- 신규 테이블 **4개**; 검색어 **6/6**
- 검색어 CRUD / Audit / 작업 멱등성 / 공고 발견 관계 Smoke: 모두 PASS
- Fixture 테스트 변경은 rollback, 기존 4개 테이블 행 수 **7/1/1/3** 유지
- 게시물 지문 `e842f12aec1cde3804813074c64a5080` 전후 동일
- 앱 DB 51개 테이블 보존: PASS
- Scheduler disabled / Fixture, Timer disabled/inactive
- T64 정책 회귀: 6/6 PASS
- 기존 Docker 볼륨·서비스 보존, Live 수집 HOLD
- **Worker E2E: 미실행 (HOLD)**. T151은 작업 메타데이터 관리이며 실제 Worker 실행 통합은 후속 일감에 포함.
- **runtime schema CREATE 권한 기존 상태로 잔존**. 이번 작업에서 추가·회수하지 않았으므로 권한 개선은 별도 보안 작업으로 추적해야 함. 필요 시 역할과 영향 확인 후 최소 권한 조정.
- 과거 테스트 데이터 폴더 cleanup 정책 차단은 별도 HOLD 유지.

## 판정
`T151_STAGING_MIGRATIONS=PASS`, `T151_METADATA_SMOKE=PASS`, `T151_FULL_E2E=HOLD`, `T151_OVERALL=HOLD`.

## 로컬 Evidence (미열람)
- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05c-evidence.json`
- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t151-step05c-execution.log`

## 다음
T152는 외부 라이브 요청 없이 **합성 목록/상세 원본을 저장하고 검증하는 Fetch/Raw 분리 기능**부터 구현. 실제 Worker E2E는 T152/T153/T154 통합 후 실행. T151 전체 DONE 판정은 이후 통합 Evidence로 확인.
