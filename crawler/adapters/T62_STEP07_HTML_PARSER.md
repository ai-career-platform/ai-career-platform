# T62 STEP 07 — 오프라인 HTML 메타데이터 파서 (실사이트 정확도 HOLD)

## 목적과 허용 경계

`crawler/adapters/jobkorea_html_offline.py`는 **외부에서 승인된 방식으로 확보한 HTML 문자열을 입력받아**, 그 안의 구조화된 `application/ld+json` / `JobPosting` 데이터를 읽는 **순수 오프라인 파서**다.

**HTTP 접근, 브라우저 자동화, JobKorea 스크래핑, DB 저장, Batch Worker 호출, 예약 실행이 없다.** 원본 사이트에 대한 접근 허가 또는 실제 페이지 구조 적합성을 주장하지 않는다.

### 결과 DTO

- 상세 URL `/Recruit/GI_Read/{숫자}`에서 `external_posting_id`를 추출하되, JSON-LD 내부 `url`/`identifier`가 있다면 일치 여부 검증
- JSON-LD의 `title`과 `hiringOrganization.name`은 반드시 존재해야 함
- `jobLocation.address`를 통한 근무지, `employmentType`, `datePosted`, `validThrough`은 있을 때만 추출
- 날짜는 기존 T62 `normalize()` 계약인 ISO 날짜로 변환; 잘못된 날짜·발행/마감 역전은 거절
- 원천 스키마에 없는 `학력/경력/급여` 필드는 현재 **정확히 파싱 불가 / 매핑 보류**. STEP 08에서 원본 확보 및 Schema 계약 확장 검토
- 고용형태가 매핑되지 않으면 `None` 유지. 채용공고 제목에 '계약직'이라는 단어가 있다는 이유로 자동 확정하지 않음
- 기업 주소는 근무지로 간주하지 않음. 출처에 명시하지 않은 값은 만들어내지 않음
- JobPosting JSON-LD가 없거나 여러 개/불일치할 때는 **실패 처리**. 다른 화면 텍스트로 추측하지 않음
- `status='published'`는 게시된 상세 페이지 형식의 DTO 임시 상태이며 **실제 접수 중/마감 여부를 검증한 값이 아님**. 운영 연계 전 상태 계약 보완 필요

## 테스트

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 T62/T63/T64 185개 + 신규 STEP 07 테스트 19개 = **총 204개 예상**. 기존 사용자 파일, 로컬 PostgreSQL 데이터, 크롤러 Worker의 구현은 변경하지 않는다.

테스트에 들어간 공고번호 `50246410`은 오직 **URL 형식 검증을 위한 식별자**다. 테스트 제목 '합성 테스트 공고'와 기업 '가상기업'은 실제 잡코리아 공고의 내용이 아니다.

## 현재 정확도 검증 판정

- 합성 HTML의 구조화된 데이터 처리 → STEP 07 로컬/CI 테스트 후 PASS 가능
- 실제 잡코리아 HTML이 JSON-LD를 포함하는지 여부 → **NOT_VERIFIED**
- 동적 렌더링/비구조화 DOM/iframe/복수 섹션에서 필요한 필드 추출 → **NOT_IMPLEMENTED**
- 실제 공고 `50246410`의 제목·회사·근무지·경력·학력·급여·마감일과 비교 → **NOT_RUN**
- 실제 추출 정확도 수치 → **NOT_MEASURABLE**

## 다음 단계

STEP 08: 접근·재사용 권한이 확보된 실제 HTML 샘플과 사람이 확인한 정답(Golden Dataset)으로 필드별 exact match/coverage/unknown/mismatch를 계산하며, 증거가 없는 필드는 미검증으로 유지한다. T61 승인 이전에는 실제 사이트 HTTP 자동 수집을 수행하지 않는다.

STEP 09: T61 허가·접근 방식·저장/재배포 권한 근거가 승인된 경우에만 실사이트 접근/네트워크 Adapter와 E2E를 검증한다. 실제 사이트 전 단계에 **HOLD** 유지.
