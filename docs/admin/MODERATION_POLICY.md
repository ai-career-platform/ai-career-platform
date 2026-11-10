# T80 — 운영 콘텐츠 검수 정책

> 상태: **DRAFT / REVIEW_REQUIRED** (PR #145 초안 → 이번 보완) · 기능: F-027 · 화면: UI-027 · 담당: 기획/보안
> **정책 승인: 미완료.** PM 승인 전까지 어떤 항목도 운영 정책으로 쓰지 않는다.
> 상태 모델: [MODERATION_STATE_DIAGRAM.md](MODERATION_STATE_DIAGRAM.md) · 후속 구현 계약(T81·T82): [MODERATION_IMPLEMENTATION_CONTRACT.md](MODERATION_IMPLEMENTATION_CONTRACT.md)

## 0. 읽는 법 — 근거 등급

| 등급 | 뜻 | 운영 사용 |
|---|---|---|
| `FACT` | main에 병합된 코드·계약·문서에 근거가 있음 (링크 표기) | 근거 범위 안에서만 |
| `REVIEW-PROPOSED` | PR #145 Crasnec 리뷰(CHANGES_REQUESTED)의 추천안. 리뷰 본문이 "예시"라고 밝혔으므로 **PM 승인 전** | 불가 |
| `PROPOSED` | 이 문서가 새로 제안 | 불가 |
| `OPEN` | 결정 필요 | 불가 |

리뷰 본문에 "확정 사항"이라는 소제목이 있었으나, 같은 리뷰가 "이번에 같이 정해주셔야 할 부분입니다. 다음 내용은 예시입니다."라고 밝혔고 PM 승인 기록이 없어 `REVIEW-PROPOSED`로 둔다.

## 1. 현재 사실 (FACT)

| 항목 | 사실 | 근거 |
|---|---|---|
| 1차 범위 | F-027은 **1차 제외** ("1차에 검수할 공개 콘텐츠 없음", T80~T82) | `docs/requirements/traceability/TRACEABILITY.md`, `docs/requirements/overview/PROJECT_OVERVIEW.md` |
| API | v0.1의 `GET·POST /admin/reviews`는 v0.2에서 **삭제** ("운영 콘텐츠 검수 1차 제외") | `docs/API_CONTRACT.md` 변경 이력 |
| DB | 검수 테이블 **없음**. `audit_events`의 F-027 연결도 제거 | `database/FULL_DATABASE_MODEL.md` |
| 역할 | `job_seeker`, `admin` 2개. 권한 `admin.models.read`, `admin.audit.read`. 기업 담당자 역할 없음 | `database/seeds/0001_initial_seed.sql` |
| 권한 검사 | 서버 의존성 `require_roles`/`require_permissions`(403), `ensure_owner`(남의 리소스 404) | `backend/app/dependencies/auth.py` |
| 오류 카탈로그 | `FORBIDDEN`(403), `NOT_FOUND`(404), `CONFLICT`·`APPROVAL_CLOSED`(409), `VALIDATION_FAILED`(422), `LAST_ADMIN`(409) 등 | `backend/app/core/errors.py` |
| 감사 action_code | `admin.content.review`(retention_class security)가 계약에 있음. 0001 `audit_events`에는 result·reason_code 칸 없음(T83 제안) | `docs/security/AUDIT_EVENT_CONTRACT.md`, 0001 |
| 공고 상태 | `job_postings.status` ∈ draft·published·closed. 등록자 컬럼 없음 | 0001 |
| 공용 자료 | `user_documents.visibility` ∈ private·shared, `owner_user_id` 있음, `status`에 `rejected`(업로드 검사 실패) | 0001, T49·T50 |
| 선행 일감 | T04 #13, T05 #17, T06 #29 모두 main 병합. 단 셋 다 F-027을 **의도적으로 제외** | GitHub PR |

→ 검수 기능 구현에는 **요구사항(T04)·데이터 사전/Migration(T05·T08)·OpenAPI(T06) 변경이 먼저** 필요하다 (구현 계약 §7).

## 2. 검수 대상과 시점

### 2.1 대상 (REVIEW-PROPOSED)

| # | 대상 | 유입 경로 | 기존 저장 위치 (FACT) | 시점 | 적용 선행조건 |
|---|---|---|---|---|---|
| 1 | 외부 수집 공고·기업 | 수집 배치 (T62) | `job_postings`, `companies` | 게시 전 + 게시 후 | T61 권리 검토 승인, T62 |
| 2 | 기업 담당자 등록 공고 | 기업 계정 (T121~) | `job_postings` (등록자 컬럼 없음 → Migration 필요) | 게시 전 + 게시 후 | 기업 계정·역할 출시 |
| 3 | 공용 RAG 자료 | 관리자 업로드 `visibility='shared'` | `user_documents` | 게시 전(색인 전) + 게시 후 | Q&A(RAG) 출시 |
| 4 | 신고된 사용자 AI 결과 | 사용자 신고 | `document_analyses`, `retrieval_runs`, `agent_runs`, `match_evaluations`, `recommendation_runs` 등 | 게시 후(신고 시)만 | 신고 기능 (요구사항·테이블 없음) |

### 2.2 제외 (REVIEW-PROPOSED)

| 제외 | 예 | 예외 |
|---|---|---|
| 본인 전용 개인 데이터 | 프로필, 보유 기술, 경력, 비공개 문서, 행동 이벤트 | 없음 |
| 본인 전용 AI 결과 | 문서 분석, Q&A 답변, 매칭·추천 결과 | **본인이 신고하면 대상 4로 검수** (아래) |
| 합성 Seed 데이터 | `data_sources.code = 'synthetic_seed'`, fixture | 없음 |
| 감사·시스템 기록 | `audit_events`, `ai_usage_records`, `ingestion_runs`, `model_versions` | 없음 |

**본인 전용 AI 결과의 예외 (PROPOSED)**
- 평소에는 검수하지 않는다. 결과는 본인에게만 보이므로 **신고자는 결과 소유자 본인뿐**이다.
- 신고하면 검수 건이 생기고, 관리자는 **신고된 결과 1건만** 볼 수 있다. 소유자의 다른 데이터는 볼 수 없다.
- 열람할 때마다 감사 기록을 남긴다.
- 신고 화면에서 "검수를 위해 관리자가 이 결과를 열람함"을 고지하고 동의를 받는다. 동의 방식은 **OPEN**(법무 확인)이다.
- 검수 결과는 그 결과의 표시 여부(숨김)와 모델 품질 피드백에만 쓴다. 사용자의 다른 데이터에는 영향을 주지 않는다.

### 2.3 게시 전 검수와 게시 후 재검수

| 구분 | 게시 전 검수 (`trigger=PRE_PUBLISH`) | 게시 후 재검수 (`trigger=REPORT·EXPIRY·SOURCE_CHANGE`) |
|---|---|---|
| 공개 상태 | 승인 전까지 **비공개**. 공고는 `draft` 유지, 공용 자료는 RAG 색인 안 함 | 결정 전까지 **공개 유지**. 단 개인정보·유해·악성 신고는 운영자가 24시간 안에 임시 비공개 검토 (§6) |
| 승인 결과 | 공개 허용 (`draft → published`, 색인 허용) | 게시 유지 |
| 반려 결과 | 비공개 유지 | **게시 중단** (공개 철회) |
| 대상 | 1·2·3 | 1·2·3·4 |
| 등급 | REVIEW-PROPOSED (리뷰 "시점: 혼합") | 재검수 계기 구분과 공개 유지 규칙은 PROPOSED |

- 승인된 콘텐츠를 다시 보는 것은 **새 검수 건**이다(상태 모델 §1). 기존 승인 기록은 바꾸지 않는다.
- 게시 중단은 삭제가 아니다. 콘텐츠와 기록은 남기고 공개만 철회한다. 공고는 `closed`로 표현할 수 없다. T18 공고 API가 `closed`도 노출하기 때문이다(FACT). 별도 표시가 필요하며 형식은 **OPEN**이다(구현 계약 §5).

### 2.4 자동 검증 실패, 자동 표시, 운영자 반려, 게시 중단 — 서로 다른 개념

| 개념 | 언제 | 하는 일 | 검수 건 | 이의제기 | 등급 |
|---|---|---|---|---|---|
| **자동 검증 실패** | 업로드·등록 단계 | **악성 파일·형식 오류만** 입력을 거부한다. 예: `user_documents.status='rejected'`(T49·T50 업로드 검사) | 만들지 않음 | 없음. 고쳐서 다시 제출 | REVIEW-PROPOSED (기존 업로드 거부는 FACT) |
| **자동 표시** | 검수 건 생성 시 | 개인정보 패턴·중복·금칙어를 찾아 **표시만**(flags). 우선순위 상향 가능 | 만듦 | — | REVIEW-PROPOSED |
| **운영자 반려** | 검수 중 | 관리자가 사유 코드와 함께 반려 (`REJECTED`) | 결정 | 1회 | REVIEW-PROPOSED |
| **게시 중단** | 게시 후 건에서 반려 | 공개 철회 (반려의 효과) | 결정 | 1회 | REVIEW-PROPOSED |

- 리뷰의 "자동 반려 허용"은 **자동 검증 실패**를 뜻하는 것으로 정리한다. 상태 모델의 `REJECTED`는 **운영자 결정만** 뜻한다. PR #145 §2.4의 충돌은 이렇게 해소한다(PROPOSED).
- 자동 처리로 사용자 콘텐츠를 **삭제하지 않는다**(REVIEW-PROPOSED).

## 3. 상태 모델 요약

[MODERATION_STATE_DIAGRAM.md](MODERATION_STATE_DIAGRAM.md)가 기준이다.
- 상태: PENDING, IN_REVIEW, APPROVED, REJECTED, APPEALED (#145 후보 유지). 결정 없는 종료용 CLOSED만 새로 **제안**한다.
- 결정된 건은 다시 열지 않는다. 재검수는 새 건으로 연다.
- 중복 요청은 열린 건을 돌려준다(멱등).
- 잘못된 전이와 동시 처리 충돌은 409를 반환한다.
- 담당자 변경은 REASSIGN, 또는 RELEASE 후 다시 ASSIGN한다.

## 4. 권한과 승인

### 4.1 역할 (REVIEW-PROPOSED + PROPOSED)

- 기존 `admin` 역할에 검수 권한을 둔다. **검수 전용 역할은 만들지 않는다**(REVIEW-PROPOSED).
- 권한 코드 `admin.content.review`를 admin 역할에 부여하고, 서버는 `require_permissions("admin.content.review")`로 확인한다(PROPOSED).
  - 기존 `admin.audit.read`와 같은 방식이고 감사 action_code와 이름을 맞췄다.
  - Seed·Migration 변경이 필요하다.
- 기업 담당자 역할은 T121에서 정한다(OPEN). 이 문서는 그 역할을 `owner`로만 다룬다.

### 4.2 역할별 권한 (PROPOSED)

| 작업 | 비로그인 | 일반 사용자 | 콘텐츠 소유자 | admin (소유자 아님) | admin (자기 콘텐츠) | admin (최초 결정자, 재검토 단계) |
|---|---|---|---|---|---|---|
| 게시 전 검수 요청 (SUBMIT) | 401 | — | 자기 콘텐츠만 | system이 생성 | 가능 (요청만) | — |
| 신고 (SUBMIT, REPORT) | 401 | 볼 수 있는 콘텐츠만 | 본인 AI 결과 | 가능 | — | — |
| 검수 큐·상세 조회 | 401 | 403 | 자기 건 상태만 (`/me`, 내부 메모 제외) | 가능 | 가능(조회만) | 가능 |
| 담당 시작·변경·해제 | 401 | 403 | 403 | 가능 | **403** | 재검토 단계 **403** |
| 승인·반려(게시 중단) | 401 | 403 | 403 | 담당자만 | **403** | 재검토 단계 **403** |
| 임시 비공개 (게시 후, §6) | 401 | 403 | 403 | 가능 | **403** | 가능 |
| 이의제기 (APPEAL) | 401 | 403 | 반려된 자기 건, 1회 | — | 자기 콘텐츠면 owner로서 가능 | — |
| 요청 철회 (PENDING → CLOSED) / 이의제기 철회 (APPEALED → REJECTED) | 401 | 403 | 자기 건 | — | owner로서 가능 | — |

- 다른 사람의 검수 건은 존재 자체를 숨긴다(404, 기존 `ensure_owner`와 같은 원칙).
- **자기 콘텐츠 직접 검수 금지:** 예를 들어 관리자가 올린 공용 RAG 자료(`owner_user_id`)는 그 관리자가 담당·승인·반려할 수 없다(REVIEW-PROPOSED).
- **재검토는 최초 결정자와 다른 관리자가 맡는다**(REVIEW-PROPOSED).
  - 관리자가 올린 공용 자료가 반려돼 이의제기하면, 재검토자는 소유자도 최초 결정자도 아니어야 한다. 그래서 **관리자가 최소 3명** 필요하다.
  - 부족하면 그 건은 HOLD로 둔다(PROPOSED).
- **관리자가 1명뿐이면** 자기 콘텐츠 건은 배정할 수 없어 PENDING에 머물고, `needs_other_admin` 표시와 기한 경고를 낸다. 우회 승인은 없다(REVIEW-PROPOSED: "보류").
- 모든 권한 판단은 서버에서 매 요청 DB 기준으로 한다(FACT: T15 인증 구조). 화면 상태나 토큰 안의 역할은 믿지 않는다.

## 5. 반려 사유와 이의제기

### 5.1 반려 사유 코드 (REVIEW-PROPOSED)

| 코드 | 뜻 | 주로 쓰는 대상 | #145 초안 코드 대응 |
|---|---|---|---|
| `RIGHTS_UNCLEAR` | 권리·출처 불명확 | 1, 3 | — |
| `INACCURATE` | 부정확·허위 정보 | 1, 2, 4 | `FALSE_INFORMATION` |
| `PERSONAL_DATA` | 개인정보 포함 | 전체 | `PERSONAL_DATA_EXPOSURE` |
| `HARMFUL` | 유해 (사기성 비용 요구 포함) | 전체 | `SUSPICIOUS_PAYMENT` (아래 OPEN) |
| `DISCRIMINATORY` | 차별 | 1, 2, 4 | — |
| `DUPLICATE` | 중복 | 1, 2, 3 | `SPAM_CONTENT`(반복 게시) |
| `EXPIRED` | 만료 | 1, 2 | — |
| `MALWARE` | 악성 파일 (업로드 후 발견분) | 3 | — |
| `OTHER` | 기타 | 전체 | `POLICY_VIOLATION` |

- 사유 코드는 **필수**다. `OTHER`이면 내부 메모가 **필수**다(1~500자, PROPOSED). 다른 코드는 메모를 선택으로 둔다.
- 메모는 검수 건에만 저장하고 관리자만 본다. **감사 기록에는 코드만** 남긴다(REVIEW-PROPOSED).
- 사용자에게는 코드별 표준 안내 문구만 보여 주고 내부 메모는 보여 주지 않는다(PROPOSED).
- 메모에 개인정보를 쓰지 않도록 화면에서 안내한다.
- **OPEN:** `SUSPICIOUS_PAYMENT`(채용 사기·입금 요구)를 `HARMFUL`에 합칠지, `FRAUD` 코드를 따로 둘지 정해야 한다. 스팸성 광고를 `DUPLICATE`에 넣을지도 정해야 한다.

### 5.2 이의제기 (REVIEW-PROPOSED, 수치는 추천안)

| 규칙 | 내용 |
|---|---|
| 신청자 | 반려된 콘텐츠의 소유자·게시 요청자. 신고자는 "유지" 결정에 이의제기할 수 없다(PROPOSED) |
| 기한 | 반려 결정 시각부터 **14일** 이내. 달력일 × 24시간으로 셀지, 영업일로 셀지는 **OPEN** |
| 횟수 | 검수 건당 **1회**. 접수하는 순간 1회로 센다(재검토 배정 시점이 아님). 이의제기를 철회하면 반려 결정이 유지되고 다시 신청할 수 없다 (PROPOSED) |
| 담당 | 최초 결정자와 **다른** 관리자 (소유자도 아님) |
| 결과 | 재검토 결과가 **최종**. 다시 이의제기하면 409 |
| 이의제기 중 공개 | 반려 효과 유지 (게시 전이면 비공개, 게시 후면 중단 상태 유지) — PROPOSED |
| 기록 | 최초 결정과 재검토 결정을 모두 보존 |

## 6. 처리 기한과 우선순위

기한과 우선순위는 **따로** 정한다.
- 우선순위는 큐에서 무엇을 먼저 볼지 정한다.
- 기한은 언제까지 끝내야 하는지(`due_at`) 정한다.

| 우선순위 (PROPOSED) | 해당 | 처리 기한 (REVIEW-PROPOSED, 1차 운영 인력 기준 가안) |
|---|---|---|
| P1 긴급 | 개인정보·유해·악성 신고 | **24시간 안에 임시 비공개 여부 판단**. 최종 결정은 P2 기한 |
| P2 신고 | 그 밖의 신고 | 영업일 2일 |
| P3 게시 전 | 게시 전 검수 | 영업일 3일 |
| (재검토) | 이의제기 | **OPEN** (추천 없음. 영업일 3일 제안 — PROPOSED) |

- 기한을 넘겨도 **자동 승인·반려하지 않는다.** 경고만 표시한다(REVIEW-PROPOSED).
- 영업일 달력(공휴일)과 기준 시간대는 **OPEN**이다. 시간대는 KST를 제안한다.
- 임시 비공개는 운영자 조치다. 신고만으로 자동 비공개할지는 **OPEN**이다(악의적 신고 남용 위험).
- 자동 표시(개인정보 패턴 등)는 우선순위를 올릴 수 있지만 기한은 바꾸지 않는다(PROPOSED).

## 7. 예외 처리 계약 요약

상세 오류 응답은 [구현 계약 §4](MODERATION_IMPLEMENTATION_CONTRACT.md). 기존 오류 카탈로그만 재사용한다(새 오류 코드 없음, PROPOSED).

| 상황 | 응답 |
|---|---|
| 비로그인 | 401 `UNAUTHENTICATED` |
| 검수 권한 없음, 자기 콘텐츠 담당·결정, 재검토 단계의 최초 결정자 | 403 `FORBIDDEN` |
| 없는 검수 건, 남의 건(일반 사용자) | 404 `NOT_FOUND` |
| 이미 결정된 건에 결정·이의제기, 이의제기 1회 초과, 14일 경과 | 409 `APPROVAL_CLOSED` |
| 허용되지 않은 전이, version 불일치(동시 처리) | 409 `CONFLICT` |
| 사유 코드 누락·알 수 없는 코드, OTHER 메모 누락, 검수 대상 아님 | 422 `VALIDATION_FAILED` |
| 중복 검수 요청·중복 신고 | 200 + 기존 열린 건 (오류 아님) |

## 8. 감사 기록 (PROPOSED, T83 계약 확장 필요)

- 모든 상태 전이마다 감사 이벤트 1건을 상태 변경과 **같은 트랜잭션**에서 기록한다. 감사 기록이 실패하면 전이도 롤백한다.
- action_code는 T83 형식을 따른다. 관리자 조치는 기존 계약의 `admin.content.review`를 쓴다. 사용자 조치용 코드는 제안 상태다. 목록은 구현 계약 §6.
- 남기는 것: 행위자, 검수 건 ID, 이전·다음 상태, 사유 코드, 결과.
- 남기지 않는 것: 메모 원문, 콘텐츠 본문, 신고자 신원 상세.
- 0001 `audit_events`에는 결과·사유 칸이 없다. T83 제안 컬럼 Migration(T84) 전에는 검수 건 이력 테이블이 결정 기록을 맡는다.

## 9. PR #145 리뷰(Crasnec, CHANGES_REQUESTED) 반영 현황

| 리뷰 항목 | 반영 위치 | 상태 |
|---|---|---|
| 필수 검수 대상 4종·유입 경로·적용 시점 | §2.1 | 반영 (REVIEW-PROPOSED) |
| 시점 혼합: 게시 전 승인, 공개 콘텐츠는 신고·만료 시 게시 후 재검수, AI 결과는 사후 | §2.3 | 반영 + 공개 유지·게시 중단 규칙 보완 |
| 자동은 표시, 운영자는 결정 / 자동 반려는 악성·형식 오류만 / 자동 삭제 없음 | §2.4 | 반영, #145의 "자동 반려 vs 운영자 결정" 충돌을 개념 분리로 해소 |
| 제외 대상 3종, 본인 전용 AI 결과는 신고 시에만 검수 | §2.2 | 반영 + 신고 시 열람 범위·감사·고지 보완 |
| A. admin 역할 재사용, 전용 역할 없음, 자기 콘텐츠 승인 금지, 관리자 1명이면 보류 | §4 | 반영 + 권한 코드·역할 매트릭스·3인 조건 보완 |
| B. 반려 사유 코드 9종, 사유 필수, OTHER 메모 필수, 감사에는 코드만 | §5.1 | 반영 + #145 코드 대응표, OPEN 2건 |
| C. 처리 기한 3종, 기한 초과 시 자동 승인 없음 | §6 | 반영 + 우선순위·기한 분리, OPEN 3건 |
| D. 이의제기 14일·1회·다른 관리자·최종 | §5.2, 상태 모델 T08·T09 | 반영 + 신청자 범위·공개 상태 보완 |

## 10. 미확정 항목 (PM·담당자 결정 필요)

1. 이 문서 전체(REVIEW-PROPOSED·PROPOSED 항목) PM 승인
2. F-027을 1차 제외에서 포함으로 바꿀지와 적용 시점 (요구사항 T04 갱신)
3. 신고 기능의 요구사항·화면·테이블 (현재 없음), 신고 시 열람 고지·동의 방식(법무)
4. `FRAUD` 코드 분리 여부, 스팸 분류
5. 14일 계산 방식(달력·영업일), 영업일 달력·시간대, 재검토 처리 기한
6. 신고만으로 자동 임시 비공개를 할지
7. 공고 게시 중단 표시 형식 (`closed`는 T18이 노출하므로 불가 — 별도 컬럼 등)
8. 관리자 3명 미만일 때 재검토 HOLD 해소 방법
9. 기업 담당자 역할·공고 등록자 컬럼 (T121)
10. 검수 기록·메모 보존 기간 (T83 retention_class와 맞춤)

## 11. 작업 제한

- 정책 승인 전 실제 사용자 콘텐츠 변경·삭제, 공유 Staging DB 변경, 운영 설정·자동배포 변경 금지.
- 이 PR은 문서와 문서 검증 테스트만 바꾼다. Backend·Frontend·OpenAPI·Migration은 바꾸지 않는다.
