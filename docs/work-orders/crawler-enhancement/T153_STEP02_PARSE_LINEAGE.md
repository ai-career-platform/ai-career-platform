# T153 STEP02 — Raw→정제 데이터 파싱 이력 저장

## 구현
- `0006_raw_parse_results.sql`: 크롤러 전용 DB에만 수동 적용하는 parse-result 테이블 1개. Raw artifact FK, postings 복합 FK, (artifact_id, parser_version) unique.
- `RawParseLedger.process(artifact_id)`: T152에 저장된 **합성 상세 HTML만** SHA 검증 후 기존 JSON-LD 파서로 정규화. 정상 결과만 기존 PostgresPostingStore UPSERT 및 KeywordStore 발견 관계 기록.
- 동일 DB 트랜잭션으로 Posting UPSERT, 발견 관계, Raw Parse 결과를 저장. 저장 실패 시 DB 변경 전체 rollback.
- malformed JSON-LD는 INVALID + error_code를 기록하고 posting INSERT 금지. 손상/분실된 파일은 저장소 복구가 필요한 예외로 유지.
- 동일 artifact+parser_version 재호출은 저장된 결과를 반환(재처리로 중복 수정하지 않음). 새 parser_version을 지정하여 버전별 이력을 추가할 수 있음.
- 여러 검색어로 발견한 동일 공고는 PostgresPostingStore 복합 ID로 중복 INSERT하지 않음.
- `parsed_at`은 DB default now(). 원본 raw HTML 파일 자체는 수정하지 않음.

## 범위 / 제한
- GitHub 오프라인 단위 테스트 + CI만 검증. 실제 PostgreSQL migration/Fixture E2E는 다음 Codex 검증 단계.
- 스테이징에는 0006 미적용. 외부 HTTP 0, Live HOLD, Timer disabled, Worker claim/Dispatcher는 동작시키지 않음.
- 기존 게시물 7건 및 앱 51테이블 보존. 0005는 사용자 보고 기준 staging 적용 PASS.
- T152 STEP05 로컬 Codex 사용자 보고: Migration 0005 PASS, Raw files 3, 메타데이터 3→6→롤백 후 0, 기존 데이터·서비스 PASS. 원본 증빙 파일은 GitHub 코디네이터가 직접 열람하지 못함.

## 검증
`python -m unittest crawler.tests.test_t153_parse_ledger -v`
`python -m unittest discover -s crawler/tests -v`

다음 격리 DB 검증: valid/invalid, 동일 버전 중복, 새 버전 재파싱, 원본→정제 FK, 멀티검색어 발견, 실패 롤백과 T151/T64 회귀.
