# T63 STEP 02 — 합성 공고 배치 품질 게이트 (읽기 전용)

## 목적 / 안전 경계

기존 T62의 `normalize()` 입력 계약을 재사용하여 **잡코리아 형태의 합성 공고**에 대해 필수값 오류, 잘못된 URL·날짜, 같은 배치 내 중복, 기존 ID의 출처 URL 변경 검토가 필요한 항목을 판정한다. 이 단계는 **검토용 순수 함수**만 추가하며 T62 Worker 실행 및 DB upsert 경로에 아직 연결하지 않는다. 실제 사이트 접근, 네트워크 요청, DB 쓰기, 정식 스키마 변경 없음.

## 분류 / 우선순위

`check_synthetic_batch(raw_records, previous=...)` 반환값:

- `accepted`: 정상 DTO의 순서 보존 튜플. 동일 `(source_code, external_posting_id)`의 첫 번째 **정상 입력**만 채택
- `issues`: 0부터 시작하는 입력 index와 비민감 `ReasonCode`만 기록. 원본 payload, URL, 개인식별정보를 오류 로그에 복사하지 않음
- `invalid`: 원천 형식 오류 (예: `MISSING_EXTERNAL_ID`, `INVALID_REQUIRED_FIELD`, `INVALID_URL`, `INVALID_DATE`, `INVALID_STATUS`, `INVALID_EMPLOYMENT`)
- `duplicate`: 배치 내부에서 이미 정상화되어 나타난 동일 ID의 후속 항목
- `review`: 과거 같은 ID의 `source_url`이 바뀌어 확인이 필요한 항목. **자동으로 재게시/삭제/새 공고로 단정하거나 저장하지 않는다**
- 건수 보존: `fetched == accepted + invalid + duplicate + review`

회사명 또는 제목이 같다는 이유만으로 다른 ID를 자동 병합하지 않는다. 이전 배치에는 있었지만 이번 배치에 없는 공고를 **삭제된 공고로 간주하지 않는다**. 수정 제목과 동일한 출처 URL은 검토 대상에서 제외하지만, 실제 저장 변경은 T62 별도 경로 책임이다.

## 실습 검증

Windows 11 저장소 루트:

```powershell
py -3.12 -m unittest crawler.tests.test_batch_gate -v
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 T62/T63 STEP 01 테스트 **58개** + 신규 STEP 02 **17개** = 전체 **75개 예상**. 실제 로컬 테스트 실행·CI를 확인하기 전에는 PASS 판정을 내리지 않는다.

## 후속 과제

- 원천 공고 삭제·비활성은 단일 배치 누락만으로 결정할 수 없으므로 명시적인 증빙/보존 정책이 필요
- 실제 공고의 재게시 여부는 동일/변경 URL만으로 확정하지 않으며 검토 플래그로 분리
- T63 STEP 03에서 품질 게이트와 Worker의 안전한 연결, 사유별 집계 출력 및 오류 보고 형식 검토
