# T153 STEP01 — 저장된 Raw HTML 독립 파싱 (Fixture)

- T152 `RawArtifactStore.read_verified`를 호출해 SHA-256이 일치하는 저장 원본을 가져옴.
- T62의 `parse_jobkorea_html` + `normalize()`를 재사용하며 외부 HTTP는 호출하지 않음.
- Raw 원본 저장과 parse 분리. invalid JSON-LD는 `INVALID` 결과로 표시하여 정제 DB 반영하지 않음.
- 선택적인 offline `process_stored_details()`는 기존 `PostingStore.upsert()`를 호출할 수 있지만 실제 운영 DB 자동 연결은 없음.
- 기록용 `PARSER_VERSION` 반환. 별도 parse 결과 DB 저장(파서 버전·시각·오류 코드·lineage)은 다음 단계에서 스키마 및 별도 트랜잭션으로 구현.
- 기존 공고 중복 방지/수정은 기존 MemoryPostingStore 혹은 PostgresPostingStore UPSERT 재사용.
- 실제 Live/Worker/Scheduler 연결 및 Timer 변경 없음.

테스트: `python -m unittest crawler.tests.test_t153_fixture_parse -v`

T152 STEP04 실제 격리 DB/파일 통합 검증 사용자 보고: `141/141 PASS` (T151 27/27, T64 92/92 포함). 로컬 로그 원본은 GitHub 코디네이터가 열람하지 못함. Staging 0005 적용은 별도이며 실시되지 않음.
