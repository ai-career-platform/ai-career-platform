# T62 STEP 09 — 잡코리아 실공고 E2E 검증 게이트 및 증빙 인수 기준

> 검토 기준: 2026-11-07 `main`의 T61 SOURCE_REGISTRY, JOBKOREA_FIELD_AND_RIGHTS_CONTRACT 및 T62 STEP 07/08 계약.  
> **CURRENT_RESULT=HOLD / REAL_FETCH=NOT_RUN / REAL_HTML=NOT_AVAILABLE / REAL_ACCURACY=NOT_MEASURABLE**  
> 이 문서는 실제 잡코리아에 접속하거나 수집 승인을 부여하지 않으며, 실 HTML·원문·개인정보를 저장하지 않는다.

## 1. 검증 대상

- 단일 대상: `https://www.jobkorea.co.kr/Recruit/GI_Read/50246410`
- 일치율 확인 대상: 공고번호·제목·기업명·근무지·고용형태·게시일·마감일
- T62 STEP07에서 미지원 중인 경력·학력·급여·지원/마감 상태는 **별도 계약 확장 및 실제 페이지 근거 확보 전 NOT_SUPPORTED**.
- 기업 소재지와 실제 근무지를 혼동해서는 안 된다. 제목 속 '계약직'이라는 표현만으로 정규화된 계약형태를 확정할 수 없다.
- 본 파일에 공고의 실제 내용이나 가상의 정답값을 기록하지 않는다. `50246410`은 지정된 테스트 대상 식별자일 뿐이다.

## 2. T61 출처 승인 게이트 (전부 확인되어야 함)

| 확인 항목 | 현재 근거 상태 | 판정 |
|---|---|---|
| 대상 페이지 URL 및 사용 목적 범위 확정 | 단일 URL 지정 | 범위만 확인 |
| 해당 웹페이지 자동접근에 적용되는 약관·robots·제한 확인 | T61 STEP04 체크리스트 미완료 | HOLD |
| 웹/API 적용조건 구분 및 별도 허가 필요성 검토 | API 약관 조사, 웹 적용조건 미확정 | HOLD |
| HTML 획득/저장·가공·내부 평가 용도 허용 확인 | 검증 가능 근거 미등록 | HOLD |
| 개인정보 제외, 요청 빈도, 403/429 및 차단 시 중단 정책 | 운영 승인·실증 미완료 | HOLD |
| PM 한정 실행 승인(범위/기간/횟수/보존 및 삭제) | 근거 미등록 | HOLD |
| 필요시 별도 서면 계약·허가 증빙 | 근거 미등록 | HOLD |

승인 판정은 `docs/data/SOURCE_REGISTRY.md`와 실제 공식 근거·PM 검토 결과에 따라 별도로 수행한다. **이 문서의 작성이나 CI PASS는 APPROVED가 아니다.**

## 3. 실제 HTML 증빙 인수 계약 (현재 0건)

T61 승인을 받은 뒤, 허용된 방법으로 확보한 단일 HTML에 대해 아래 메타데이터를 **코드 저장소와 분리된 승인된 저장 위치**에 작성한다.

| 키 | 필수 여부 | 검증 규칙 |
|---|---|---|
| `source_url` | 필수 | 위 URL과 완전 일치 |
| `external_posting_id` | 필수 | `50246410` |
| `collected_at_utc` | 필수 | timezone-aware UTC |
| `acquisition_method` | 필수 | T61 승인 방식과 일치 |
| `approval_reference` | 필수 | 유효한 T61 승인 근거 참조 |
| `sha256` | 필수 | 원본 HTML 파일 SHA-256 |
| `evidence_location` | 필수 | 접근통제된 보관 위치. PR/공개 저장소에는 원문 넣지 않음 |
| `reviewer`·`reviewed_at_utc` | 필수 | 사람 검수 책임자·시각 |
| `retention_deadline` | 필수 | 승인된 보존기간 준수 |
| `golden_fields` | 필수 | 개별 필드별 정답값·화면 근거·`NOT_VERIFIED` 표시 |

모든 `golden_fields`는 같은 게시물의 동일한 시점을 기준으로 검수한다. 원천 수정·마감/삭제가 일어난 경우 변경 전후 내용을 동일 정답으로 혼합하지 않는다. 첨부파일·연락처·개인정보는 기본 수집 대상에서 제외한다.

## 4. 검증 수행 순서 (승인 이후에만)

1. T61 레지스트리의 `APPROVED`, 허용된 `WEB` 획득 방법, `enabled`, URL/필드·횟수·보존기간 및 유효한 증빙을 독립적으로 확인한다.
2. 허용된 **단일** 원본 HTML을 확보하고 `sha256`·시각·출처를 기록한다. 403/429/CAPTCHA/차단·금지 조건에서는 즉시 중단하며 우회하지 않는다.
3. 원본의 `JobPosting` JSON-LD 존재 여부부터 확인한다. STEP07 파서가 JSON-LD를 지원하지 않는 실제 화면이라면 `PARSER_GAP`으로 기록하고 추정값으로 대체하지 않는다.
4. `parse_jobkorea_html(html=..., source_url=...)` 결과와 사람이 검수한 Golden Truth를 비교한다.
5. `evaluate_html(GoldCase(...), html=...)`의 필드별 `MATCH/MISMATCH/MISSING/NOT_VERIFIED/NOT_SUPPORTED` 및 정량 점수를 산출한다.
6. 실제 사이트 비교 수치는 **사람의 HTML 출처 및 T61 승인 근거 검수**가 완료된 경우에만 별도 결과보고서에 기록한다. 현재 코드 `real_site_accuracy_verified`는 안전상 항상 `false`로 출력하므로 이를 임의로 수정하거나 PASS로 보고하지 않는다.
7. 필수 필드 오류·DOM 구조 미지원·빈 값은 수정/재검증 후에만 통과. 근무지·급여·경력·학력 등 필드 지원 확대는 별도 데이터 계약 검토.
8. 실제 사이트 접근 검증 완료 후에도 운영 스케줄/DB 이관은 T09·T28 및 별도 PM 승인 후 진행한다.

## 5. 완료 기준 및 현재 결과

| 게이트 | 성공 기준 | 현재 |
|---|---|---|
| STEP07 합성 HTML 파서 | Windows+CI 정상 | PASS (PR #72 병합 당시 204 테스트) |
| STEP08 평가기 | Windows+CI 정상 | PASS (PR #73 병합 당시 225 테스트) |
| STEP09 출처 권한 | T61 승인·공식 근거 확인 | HOLD |
| STEP09 실제 HTML 원본 | 허용된 방식의 SHA·시각·보존 근거 | NOT_AVAILABLE |
| STEP09 실제 정확도 | 검수된 Golden Truth vs 추출 결과 | NOT_MEASURABLE |
| 운영 수집 활성화 | T61/T09/T28/보안/PM 승인 모두 충족 | HOLD |

**T62 전체 상태=PARTIAL.** 기존 합성 테스트 통과는 실제 웹사이트 HTML 파싱 정확도를 입증하지 않는다. 이 문서의 추가/PR/CI만으로 STEP09를 PASS로 표시하지 않는다.
