# T101 — 지원 준비·지원 상태 추적 데이터 계약 (PROPOSED)

> 상태: **PROPOSED / 미승인** — 신규 확장 기능입니다. PM 승인 전에는 T102(API)·T103(화면)이 운영에서 켜지지 않습니다.
> 기준 main `ceee31d` · 2026-11-11 · F-012·F-013 · 신규 요구사항 **FR-JOB-008(제안)** · 화면 **UI-N05(제안)**
> 선행: T04·T05·T18 병합, T91 범위 기준선(병합, 확장 후보) · 산출물: 이 문서 · [제안 DDL](../../database/proposed/T101_job_applications.sql) · [제안 OpenAPI](t101_openapi_proposal.yaml) · [계약 시험](test_t101_application_contract.py)

## 1. 범위와 원칙

| 구분 | 내용 |
|---|---|
| 하는 것 | 로그인 사용자가 **스스로** 관심 공고의 지원 준비·지원·면접·결과를 기록하고 메모·일정을 남김 |
| 하지 않는 것 | 채용사·잡코리아의 실제 지원 접수·결과 조회·연동, 지원서 제출, 알림 발송(T96 연계는 별도 승인), 다른 사람과 공유 |
| **표시 원칙** | 상태는 **"내가 기록한 상태"**이며 기업의 공식 결과가 아닙니다. 화면·API 설명·필드 이름에서 공식 결과로 오해할 표현을 쓰지 않습니다(예: "합격 확정" 대신 "합격·제안(내 기록)") |
| 대상 공고 | v1은 이 서비스의 공고(`job_postings`)만. 외부 공고 직접 입력은 DEFER(D-1) |
| 저장한 공고와의 관계 | 북마크(FR-JOB-007)와 **별개**. 화면에서 "지원 현황에 추가"를 제안할 수 있으나 자동 동기화하지 않음(D-2) |

## 2. 요구사항 FR-JOB-008 (제안)

| 항목 | 내용 |
|---|---|
| 요구사항명 | 개인 지원 현황 기록 |
| 우선순위 | Could (MVP 이후 확장) |
| 사용자 스토리 | 구직자로서, 지원하려는·지원한 공고의 진행 상황을 한곳에서 관리하고 싶다. 일정과 준비를 놓치지 않기 위해서다. |
| 입력 | 공고, 단계, 지원일, 다음 일정, 메모 |
| 출력 | 내 지원 기록 목록(단계별), 공고 마감 여부 |
| 선행 조건 | 로그인 |
| 수용 기준 | 1. 본인 기록만 보고 바꿀 수 있다(남의 기록 ID → 404).<br>2. 같은 공고는 한 번만 기록된다(409).<br>3. 허용된 단계 이동만 된다(§4, 그 외 409).<br>4. 동시에 고치면 나중 저장이 거절된다(version, 409).<br>5. 공고가 마감되면 "마감"으로, 삭제되면 "공고 정보 없음"으로 보이고 기록은 남는다.<br>6. 기록을 지우면 즉시 사라지고, 탈퇴 시 모두 삭제된다.<br>7. 화면에 "내가 기록한 상태이며 기업의 공식 결과가 아닙니다"를 표시한다. |
| 예외 처리 | 기록 없음: "아직 기록한 지원이 없습니다" + 공고 탐색 버튼 |
| 관련 화면 | UI-N05 지원 현황 보드, UI-012 공고 |

## 3. 데이터 (ERD)

```
users 1 ──< job_applications >── 0..1 job_postings
             (user_id CASCADE)      (job_posting_id SET NULL + 제목·기업명 스냅샷)
```

| 열 | 규칙 |
|---|---|
| `application_id` | UUID |
| `user_id` | 소유자. 탈퇴 시 **삭제(CASCADE)** — T87 분류 `DELETE` |
| `job_posting_id` | 공고. 공고가 지워지면 NULL, 기록은 유지 |
| `posting_title`, `company_name` | 기록 시점 스냅샷(공고 삭제 후에도 무엇이었는지 보이게) |
| `stage` | §4의 7단계 |
| `applied_on` | 지원일(KST 날짜). `interested`·`preparing`이면 없음, `applied`·`interviewing`·`offered`·`rejected`이면 반드시 있음(없으면 서버가 오늘로 채움), `withdrawn`은 둘 다 가능. 미래 날짜 불가 |
| `next_step_on` | 다음 일정(면접 등). 2000-01-01 ~ 오늘+2년 |
| `memo` | 0~2000자. **민감정보(주민등록번호·건강·연락처 등)를 쓰지 말라는 안내**를 화면에 표시. 로그·분석·AI·관리자 화면에 쓰지 않음 |
| `version` | 1부터, 수정할 때마다 +1 (낙관적 잠금) |
| `created_at`, `updated_at`, `stage_changed_at` | 서버 시각 |

- 한 사용자당 기록 최대 **500건**(D-3).
- 같은 (사용자, 공고)는 1건(UNIQUE). 공고가 지워져 NULL이 된 기록끼리는 겹칠 수 있음.

## 4. 단계와 이동 규칙

| 단계 | 화면 이름 | 의미(사용자 기록) |
|---|---|---|
| `interested` | 관심 | 지원을 고민 중 |
| `preparing` | 지원 준비 | 서류 준비 중 |
| `applied` | 지원 완료 | 내가 지원했다고 기록 |
| `interviewing` | 면접 진행 | 면접·과제 진행 중이라고 기록 |
| `offered` | 합격·제안(내 기록) | 제안을 받았다고 기록 |
| `rejected` | 불합격(내 기록) | 결과를 받았다고 기록 |
| `withdrawn` | 지원 취소 | 지원하지 않기로 함 |

허용 이동(같은 단계 유지는 항상 허용 — 메모·날짜만 수정):

| 현재 | 이동 가능 |
|---|---|
| `interested` | `preparing`, `applied`, `withdrawn` |
| `preparing` | `interested`, `applied`, `withdrawn` |
| `applied` | `preparing`, `interviewing`, `offered`, `rejected`, `withdrawn` |
| `interviewing` | `applied`, `offered`, `rejected`, `withdrawn` |
| `offered` | `interviewing`, `withdrawn` |
| `rejected` | `interviewing` |
| `withdrawn` | `interested` |

- 뒤로 가는 이동(`applied → preparing`, `interviewing → applied`, `offered/rejected → interviewing`)은 **잘못 누른 것을 바로잡는 용도**입니다.
- `preparing`이나 `interested`로 돌아가면 `applied_on`을 지웁니다.
- `withdrawn → interested`는 "다시 관심"입니다.
- 그 밖의 이동은 409 `INVALID_STAGE_TRANSITION`입니다.

## 5. API (제안, `/api/v1/me/job-applications`, 로그인 필수)

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `GET /me/job-applications?stage=&limit=&cursor=` | stage 0~7개(OR), limit 1~100 | `{ items: JobApplication[], next_cursor }` 최근 수정순 | 400 cursor, 422 |
| `POST /me/job-applications` | `{ job_posting_id, stage?, applied_on?, next_step_on?, memo? }` | 201 `JobApplication` | 404 공고 없음(draft 포함), 409 `APPLICATION_EXISTS`·`APPLICATION_LIMIT`, 422 |
| `GET /me/job-applications/{id}` | | `JobApplication` | 404(없음·남의 것 구분 안 함) |
| `PATCH /me/job-applications/{id}` | `{ version, stage?, applied_on?, next_step_on?, memo? }` (null = 지움) | `JobApplication` | 404, 409 `INVALID_STAGE_TRANSITION`·`VERSION_CONFLICT`, 422 |
| `DELETE /me/job-applications/{id}` | | 204 | 404 |

`JobApplication` = `{ application_id, stage, applied_on, next_step_on, memo, version, created_at, updated_at, stage_changed_at, posting: { job_posting_id|null, title, company_name, status: published|closed|unavailable, expires_at|null } }`
- `posting.status`: 공고가 있으면 T18 표시 상태(게시 중/마감), 지워졌으면 `unavailable`.
- 목록 응답에도 `memo`가 포함됩니다(본인만). 로그에는 남기지 않습니다.
- `memo`·제목은 일반 문자열로만 다룹니다(HTML 해석 금지 — 화면은 텍스트로 출력).

## 6. 개인정보·보존

| 항목 | 정책(제안) |
|---|---|
| 처리 근거 | 회원이 직접 입력한 서비스 이용 기록(별도 동의 불필요 — 법무 확인 D-4) |
| 보존 | 계정이 있는 동안. 사용자가 지우면 **즉시 물리 삭제**(소프트 삭제 없음) |
| 탈퇴 | 탈퇴 처리(purge) 시 CASCADE 삭제 — T87 `RETENTION_MAP`에 `job_applications.user_id: DELETE`를 추가해야 함(migration 승인 시) |
| 접근 | 본인만. 관리자 API 없음. 감사 이벤트로 내용(memo)을 남기지 않음 |
| 이용 제한 | 추천·분석·AI·통계에 쓰지 않음(쓰려면 별도 동의·승인) |
| 내보내기 | 데이터 내보내기 기능이 생기면 포함 |

## 7. 시험 (계약 시험이 확인)

- §4 이동 표를 읽어 참조 상태 기계와 비교(모든 단계 쌍 49개)
- 지원일·메모·날짜 규칙
- 제안 OpenAPI를 실제 계약에 합쳐 프로젝트 검사기 통과(FR-JOB-008 주입)
- 제안 DDL을 **일회용 PostgreSQL**에 적용해 제약 확인(환경이 없으면 건너뜀 — CI가 docs 시험을 돌리지 않으므로 로컬 결과)
  - 중복 409 근거(UNIQUE)
  - 단계별 지원일 CHECK, 메모 2000자
  - 사용자 삭제 → CASCADE, 공고 삭제 → SET NULL과 스냅샷 유지

## 8. 결정 필요 (PM·법무)

| # | 결정 | 제안 |
|---|---|---|
| D-1 | 외부 공고 직접 입력 | v1 제외 |
| D-2 | 북마크와 통합 여부 | 별개 유지, 화면에서 연결만 |
| D-3 | 사용자당 500건 상한 | 승인 |
| D-4 | 처리 근거·보존(동의 불필요 판단) | 법무 확인 |
| D-5 | 단계 이력(언제 무엇으로 바꿨는지) 저장 | v1 제외(`stage_changed_at`만) |
| D-6 | 일정 알림(T96 연계) | 별도 승인 후 |
| D-7 | 신규 오류 코드 4개(`APPLICATION_EXISTS`, `APPLICATION_LIMIT`, `INVALID_STAGE_TRANSITION`, `VERSION_CONFLICT`) | 승인 |
