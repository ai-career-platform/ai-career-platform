# 기업 공고 게시·검수·수정 정책 (T125)

> 상태: **PROPOSED**(PM·법무 승인 전)이며, 구현과 DB 변경은 없습니다.
> - 원본: [`t125_posting_state_machine.json`](t125_posting_state_machine.json)
> - 시험: `backend/tests/test_t125_posting_state_machine.py`
> - 선행: T18(공고 API)·T80(검수 정책 DRAFT)은 main에 있고, T121은 #210(미병합)입니다. 이 PR은 T121 위에 쌓여 있습니다.

## 1. 현재 사실

| 항목 | 사실 |
|---|---|
| 공개 공고 | `career.job_postings`(status draft·published·closed, `source_id` 필수). **등록자 열이 없고**, 모든 공고가 수집 데이터입니다 |
| 출처 | `career.data_sources`(`code`, `license_ref` 필수 — 합성 seed 제외) |
| 검수 | T80 정책·상태 모델(PENDING·APPROVED·REJECTED·APPEALED 등)은 DRAFT이고, 검수 표가 없습니다. 1차 범위에서 제외되어 있습니다 |
| 기업 역할 | 없음. T121에서 제안합니다(#210) |

## 2. 설계 원칙

1. **초안과 공개를 분리합니다.**
   - 기업 공고는 별도 표(제안: `organization_job_postings`)에서 작성·검수합니다.
   - **운영 승인(`posting.publish`) 때만** 공개 표 `job_postings`에 행이 생기거나 바뀝니다.
   - 그래서 기존 공개 검색 API(T18·T99)는 바꾸지 않아도 초안을 노출하지 않습니다.
2. **검수 우회를 막습니다.** 기업 역할에는 게시 전이가 없습니다. 게시·반려는 그 조직의 멤버가 아닌 운영 관리자만 합니다(T80의 `not self`).
3. **출처를 표준화합니다.** 직접 등록 공고의 출처는 다음과 같이 둡니다.
   - `data_sources.code = company_direct`, 화면 표기 "기업 직접 등록"
   - 검증된 조직(`organizations.status = active`)만 게시할 수 있습니다.
   - 수집 공고는 지금처럼 원문 링크·수집 출처를 표시합니다.

## 3. 상태

| 상태 | 공개 | 종료 | 설명 |
|---|---|---|---|
| `draft` | 아니오 | 아니오 | 작성 중. 기업만 보임 |
| `pending_review` | 아니오 | 아니오 | 검수 대기. 내용은 수정할 수 없고, 철회하면 draft로 돌아감 |
| `rejected` | 아니오 | 아니오 | 반려. 사유 코드와 설명을 보여 줌. 수정하면 draft |
| `published` | **예** | 아니오 | 게시. 공개 표에 반영 |
| `closed` | 아니오 | 예 | 기업·운영이 마감 |
| `expired` | 아니오 | 예 | 만료 시각 경과(시스템) |
| `taken_down` | 아니오 | 예 | 운영 강제 내림(사유 필수) |

## 4. 전이

| 출발 → 도착 | 행동(T121) | 수행자 | 조건 | 부수 효과 |
|---|---|---|---|---|
| `draft → pending_review` | `posting.submit_review` | 기업 담당자·관리자 | 조직 active, 필수 항목 완비, version 일치 | 검수 건 생성(T80 PENDING) |
| `pending_review → draft` | `posting.withdraw_review` | 기업 담당자·관리자 | version 일치 | 검수 건 종료(철회) |
| `pending_review → published` | `posting.publish` | **운영 관리자** | 그 조직 멤버 아님, 조직 active, 만료 ≤ 게시+60일, version 일치 | 공개 표 반영, 검수 건 승인 |
| `pending_review → rejected` | `posting.reject` | **운영 관리자** | 그 조직 멤버 아님, **사유 코드 필수**, version 일치 | 검수 건 반려 |
| `rejected → draft` | `posting.draft_edit` | 기업 담당자·관리자 | version 일치 | — |
| `published → closed` | `posting.close` | 기업 담당자·관리자, 운영 | version 일치 | 공개 표 마감 |
| `published → expired` | (시스템) | 시스템 | 현재 > `expires_at` | 공개 표 마감 |
| `published → taken_down` | `posting.takedown` | **운영 관리자** | 사유 코드 필수 | 공개 표 마감, 기업에 사유 표시 |

- 정의되지 않은 전이는 모두 거부합니다(409 `CONFLICT`).
- 종료 상태에서 다시 게시하려면 **복사해 새 초안**을 만듭니다.

### 4.1 게시 중 수정 (수정본)

- 게시 중인 공고를 고치면 **수정본**을 만듭니다. 수정본만 `draft → pending_review → published|rejected`를 거칩니다.
- **승인 전까지 공개 공고는 이전 내용 그대로**입니다. 공개 내용이 바뀌는 순간은 `posting.publish`뿐입니다.
- 마감(`posting.close`)은 수정이 아니므로 바로 반영합니다.

## 5. 내용 기준 (반려 사유 코드)

| 코드 | 기준 |
|---|---|
| `missing_required_info` | 제목·직무 설명·고용형태·근무지·마감일 누락 |
| `discriminatory_requirement` | 성별·연령·출신지·혼인 여부 등 직무와 무관한 차별적 요건(**법무 확인 필요**) |
| `personal_contact_info` | 개인 휴대전화·개인 이메일 게시. 회사 채널만 허용 |
| `misleading_terms` | 실제와 다른 고용형태·급여 표현, 비용을 요구하는 공고 |
| `not_a_job_posting` | 광고·교육 판매 등 채용이 아님 |
| `duplicate_posting` | 같은 조직의 같은 공고가 이미 게시 중 |
| `unverified_link` | 지원 링크가 https가 아니거나 조직 도메인과 무관 |
| `other` | 설명 필수 |

내림 사유: `legal_request`, `fraud_suspected`, `discriminatory_requirement`, `organization_suspended`, `other`.

## 6. 불변 조건 (시험으로 고정)

| ID | 조건 |
|---|---|
| P-INV-1 | 기업 역할은 `published`로 가는 전이를 실행할 수 없다 |
| P-INV-2 | 게시·반려는 해당 조직 멤버가 아닌 운영 관리자만 한다 |
| P-INV-3 | 공개 표는 `posting.publish` 때만 생기거나 바뀐다. 초안·검수 중·반려는 공개 API에 나오지 않는다 |
| P-INV-4 | 반려·내림에는 사유 코드가 필수다 |
| P-INV-5 | `closed`·`expired`·`taken_down`은 종료 상태다 |
| P-INV-6 | 운영 관리자는 공고 내용을 수정하지 않는다 |
| P-INV-7 | 사람이 수행하는 모든 전이는 version 일치가 필요하다(동시 수정 409) |
| P-INV-8 | 검증 전·정지 조직은 검수 요청·게시를 할 수 없다 |

## 7. 결정 필요 (PM·법무)

| ID | 항목 | 제안 |
|---|---|---|
| D-1 | 초안·공개 분리 | 별도 표 + 승인 시 공개 표 반영 |
| D-2 | 최대 게시 기간 | 60일 |
| D-3 | 검수 처리 기한 | 영업일 2일(T80 기한 모델 준용). 기한이 지나도 자동 승인하지 않음 |
| D-4 | 차별 요건 기준 | **법무 검토 필요**(관련 법령 확인) |
| D-5 | 이의 제기 | T80 APPEALED 흐름 재사용 여부 |
| D-6 | 출처 표기와 약관 | `company_direct`, `license_ref`는 조직 게시 약관 버전(약관 작성 필요) |
