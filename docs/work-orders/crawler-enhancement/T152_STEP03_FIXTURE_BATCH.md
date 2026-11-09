# T152 STEP 03 — 합성 목록·상세 Raw HTML 일괄 저장

기존 T62 `parse_jobkorea_list_html`은 **URL 발견 용도만** 재사용. T152의 `RawArtifactStore`는 내용 파싱 없이 수신된 합성 HTML 바이트 그대로 보존하고, `RawArtifactMetadata`는 검색어·URL·해시·크기 및 작업 FK를 기록한다.

- 합성 목록 1건에서 중복 제거된 상세 링크 최대 10건을 찾고, **호출자가 제공한 상세 HTML만** 매칭한다.
- 누락되거나 초과된 상세 URL, 잘못된 HTML 바이트, 잘못된 검색어 등은 **파일 쓰기 전에** 실패한다.
- 실제 HTTP 요청, worker dispatch, 스케줄, JSON-LD 파싱, 정규화, posting UPSERT는 없음.
- 동일 배치 재시도 시 기존 복합키 멱등성 유지, 서로 다른 키워드는 별도의 메타데이터 UUID와 동일 content-addressed 파일 공유.
- 원자성 한계: 여러 파일과 DB 메타데이터는 하나의 트랜잭션이 아님. 부분 장애 시 재시도·고아 파일 수동 검사를 활용하고 파일 자동 삭제는 금지.
- 초기 범위는 합성 fixture **오프라인 E2E**이며, `0005` 실제 스테이징 적용과 DB 기반 Worker E2E는 하지 않음.

검증: `python -m unittest crawler.tests.test_t152_fixture_raw_batch -v`; `python -m unittest discover -s crawler/tests -v`.

## T152 STEP 02_RETEST 참고

사용자 제공 Codex 보고: `134/134 PASS`, 실제 DB 검사 `8/8 PASS`, T151 `27/27`, T64 `92/92`. 기존 PK 충돌이 해결됐고 격리 DB 종료, 스테이징 데이터 변경 없음. 원본 로그는 GitHub에서 직접 열람하지 못한 것으로 구분한다.
