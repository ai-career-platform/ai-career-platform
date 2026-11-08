# T152 STEP01 — Fixture Raw HTML Storage

## 구현 범위
- `crawler/storage/migrations/0005_raw_artifacts.sql`: 스테이징 크롤러 전용 DB에 수동 적용하는 Raw 메타데이터 테이블 **1개**. 0003 선행. 기존 테이블 변경 없음.
- `crawler/jobs/raw_artifact_store.py`: 합성 목록/상세 HTML의 **원본 bytes를 정확하게 저장**, SHA-256 조회 검증, 파일과 DB 메타데이터 분리.
- `crawler/tests/test_t152_raw_artifacts.py`: 외부 HTTP·DB 없는 offline unit tests.

## 안전한 의도적 제한
- 합성 Fixture만 지원. 실제 JobKorea HTTP를 호출하는 함수를 새로 연결하지 않음.
- Raw 단계에서 HTML 링크 파싱, 공고 정규화, UPSERT를 수행하지 않음. 파서 연계는 T153의 책임.
- 작업 id/검색어별 provenance는 FK metadata로 유지.
- 파일은 SHA-256 기반 key로 중복 저장을 막으며 파일 손상을 해시로 검증.
- 새 원본 저장 디렉터리는 기존 앱 DB Docker volume 및 운영 데이터 디렉터리와 구분. 기존 백업/정책 차단 테스트 폴더 삭제 금지.
- **파일 쓰기와 DB insert는 하나의 원자적 트랜잭션이 아님.** DB 실패 시 남은 고아 파일은 재검사/재시도 가능하며 자동 삭제하지 않음.
- 외부 HTTP 수집·robots/403/429 차단·실제 데이터 보존 정책 연동은 후속 Live gate 및 T152 추가 작업에서만 검토.

## 검증
`python -m unittest crawler.tests.test_t152_raw_artifacts -v`
`python -m unittest discover -s crawler/tests -v`

## 상태
GitHub fixture-only initial implementation. 실 DB에 0005 적용 안 함. Staging Fixture E2E 별도 검증 필요.
