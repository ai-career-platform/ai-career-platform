# T152 STEP02 — RawReceipt 검색어 간 재사용 시 PK 충돌 수정

## 오류와 원인

로컬 Codex 격리 PostgreSQL 검사 7/8 PASS, `MULTI_KEYWORD_REFERENCE=FAIL` (사용자 제공 결과). 동일 `RawReceipt`를 검색어 A와 B에 연결할 때 `RawArtifactMetadata.insert()`가 `receipt.artifact_id`를 그대로 `raw_artifacts.artifact_id`로 재사용하여 PK 충돌 발생.

## 최소 수정

- **파일 식별**: `sha256` 및 `storage_key`는 검색어 사이에 공유하고 바이트 중복 저장 없음.
- **DB 행 식별**: `RawArtifactMetadata.insert()`마다 새 `uuid4()`를 할당하여 서로 다른 검색어 행의 PK가 충돌하지 않게 수정.
- **동일 검색어 멱등성**: 기존 UNIQUE(`keyword_id,kind,source_url,sha256`) 및 `ON CONFLICT ... DO NOTHING` + 기존 행 조회를 유지.
- 기존 `0005_raw_artifacts.sql` 및 기존 스테이징 DB를 수정하지 않음.
- 추가 오프라인 회귀: *동일 receipt 두 검색어 저장 → metadata PK 상이 / storage key 동일; 검색어 A 반복 저장 → 기존 PK 반환*.

## 검증 경계

기존 실패 증빙 (사용자 제공 경로, GitHub에서 원본 로그 미열람):
- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t152-step02-evidence.json`
- `C:/Users/gmoon/Documents/Codex/2026-11-07/files-pasted-by-the-user-ai/outputs/t152-step02-raw_pg.log`

GitHub CI/offline test는 DB 에뮬레이터 계약 검증이며 **실제 PostgreSQL 검증이 아님**. 수정 후 Codex가 격리 PostgreSQL에서 8/8 재검증 및 T151/T64 회귀를 수행해야 STEP02 PASS 가능.

기존 staging 상태, 원본 데이터, Timer, Live 수집은 변경하지 않음.
