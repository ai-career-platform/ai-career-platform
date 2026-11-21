# T96 — 이메일·서비스 알림 이벤트 발송 모듈

> 상태: **PARTIAL** — 모듈·시험 완료, 운영 발송은 **HOLD**(메일 공급자 미정, 템플릿 전부 미승인, outbox 표 제안 단계).
> 기준: [T95 알림 계약](T95_NOTIFICATION_CONTRACT.md)(PROPOSED) · [수신 설정 매트릭스](T95_PREFERENCE_MATRIX.md) · main `ceee31d` · 2026-11-11
> 기능 ID: F-003, F-005 · 선행: T14·T15(병합), T95(병합, 계약은 PROPOSED)

## 1. 무엇을 만들었나

| 파일 | 역할 |
|---|---|
| `backend/app/services/notifications.py` | 유형 10종 사양(T95 표와 시험으로 일치 고정), 템플릿 등록부, 접수(`NotificationDispatcher`), 발송 worker(`NotificationWorker`), 공급자 계약(`Unavailable`/`Mock`), 마스킹, 메모리 구현 |
| `backend/app/repositories/notifications.py` | PostgreSQL outbox(`SqlNotificationOutbox`)·수신자 조회(`SqlRecipientDirectory`, `users.status` + `user_consents` 최신 행) |
| `database/migrations/0005_notifications.sql` | outbox 표 + T97 알림함 `read_at`·수신 설정 표(migration 0005). 운영(GCP) 적용은 별도 PM 승인 |
| `backend/tests/test_t96_notifications.py` | 단위 21건 (메모리 outbox·Mock 공급자) |
| `backend/tests/test_t96_notifications_postgres.py` | 일회용 PG 7건 (migration 0005·최소 권한 역할·동시성) |

API 경로는 추가하지 않았습니다(수신 설정 API는 T95 제안 단계, 알림함 API는 계약 없음 → T97 참고).

## 2. 처리 흐름

```
이벤트 ─▶ Dispatcher.enqueue
          ├─ 유형·템플릿 승인·비밀 변수·변수 이름 검사 (위반 = ValueError, 기록 없음)
          ├─ 수신자 없음 → unknown_recipient / 비활성 → blocked_inactive (탈퇴 안내만 예외)
          ├─ 선택 알림 동의 없음(최신 행 기준, 기본값 표대로) → blocked_consent
          └─ 묶음 키 sha256(user|type|subject) 중복 → duplicate, 아니면 queued (조용한 시간이면 다음 08:00 KST)
outbox ─▶ Worker.run (명시적 1회 실행, 스케줄 없음)
          ├─ 공급자 미설정 → 아무 행도 꺼내지 않음
          ├─ FOR UPDATE SKIP LOCKED 로 due 행 점유(5분). 점유 만료 행은 중단된 worker 로 보고 회수
          ├─ 발송 직전 재확인: 비활성/삭제 → cancelled, 동의 철회 → cancelled, 템플릿 미승인·버전 변경 → failed_permanent
          ├─ 조용한 시간 → queued(다음 08:00)
          └─ 공급자 호출: 성공 sent / 일시 실패 백오프 1분→5분→30분→2시간→6시간(유형별 최대 횟수 후 failed)
                         / 영구 실패 failed_permanent(재시도 없음)
```

## 3. 설계 결정 (리뷰 대상)

| # | 결정 | 이유 |
|---|---|---|
| D1 | 운영 기본값은 **아무것도 보내지 않음**: 공급자 `Unavailable`, 템플릿 전부 미승인 | 메일 공급자·템플릿 승인 전 실발송 금지 |
| D2 | **비밀 변수(링크·토큰)가 있는 템플릿은 outbox에 넣지 않음** | T95 §6 "링크·토큰 저장 금지". 비밀번호 재설정·이메일 인증은 T93의 즉시 발송 경로 유지 |
| D3 | 수신 주소는 저장하지 않고 발송 시점에 `users`에서 조회 | 주소 원문 저장 금지, 이메일 변경 반영 |
| D4 | 중복 방지 = advisory lock 직렬화 + 창 안 기존 행 확인 + 부분 unique index | 동시 요청 8건 → 1건 (PG 시험) |
| D5 | 최소 1회 전달. 공급자에 `delivery_id`를 멱등 키로 전달 | worker가 발송 후 기록 전에 중단되면 회수 시 다시 보낼 수 있음 → 공급자 측 멱등 처리 필요(공급자 선정 조건) |
| D6 | 사용자 시간대는 KST 고정 | `users`에 시간대 열 없음 |
| D7 | 탈퇴 시 `user_id` SET NULL (T87 분류 ANONYMIZE), 남은 대기 행은 취소 | 보존 기간 동안 발송 사실만 남김 |
| D8 | 보존 기간 정리 `purge_expired`는 처리 끝난 행만, 실행 스케줄 없음 | 보존 기간은 법무 확인 전 제안값 |

## 4. 시험 결과 (로컬, Windows 11 · Python 3.12 · PostgreSQL 18.6 일회용 클러스터)

| 범주 | 시험 | 결과 |
|---|---|---|
| 계약 일치 | 유형 10종의 필수·동의·기본값·채널·조용한 시간·창·재시도·보존을 T95 표에서 읽어 비교 | PASS |
| 거부 | 미승인 템플릿·비밀 변수·변수 이름 불일치·모르는 유형 → 기록 없음 | PASS |
| 동의 | S1 마케팅 철회 차단, S2 필수 발송, S3 기본 끔, 서비스 안내 기본 켬·철회 | PASS |
| 계정 상태 | S6 비활성 계정은 탈퇴 안내만, 발송 직전 비활성화 → cancelled | PASS |
| 중복 | S7 창 안 차단·창 밖 재허용, **동시 접수 8건 → 1행(PG)** | PASS |
| 조용한 시간 | S4 23:00 → 다음 08:00, S5 보안 즉시, 07:59 경계 | PASS |
| 재시도 | 일시 실패 백오프 후 성공, S9 최대 횟수 → failed, 영구 실패 재시도 없음 | PASS |
| 회복 | 점유 후 중단된 행 5분 뒤 회수(메모리·PG), **동시 worker 4개 40건 → 중복 0(PG)** | PASS |
| 개인정보 | 로그·repr·DB 행에 주소 원문·본문·링크 없음(마스킹 `g***@domain`) | PASS |
| DB 제약 | 상태·채널·횟수·변수 형식·키 형식·sent_at 일관성 CHECK, 앱 역할은 `users` 변경 불가 | PASS |
| 보존 | 유형별 기간, 대기 행 보존 | PASS |

실행:

```powershell
cd backend
python -m pytest -q tests/test_t96_notifications.py
$env:T16_ISOLATED_DB_TEST="YES"; $env:T16_TEST_ADMIN_URL="postgresql://<admin>@127.0.0.1:<port>/t16_profile_test"
python -m pytest -q tests/test_t96_notifications_postgres.py
```

CI(`backend-tests.yml`)는 PostgreSQL 18.1 서비스에서 두 파일을 모두 실행합니다.

## 5. 하지 않은 것 / HOLD

| 항목 | 상태 | 필요한 결정 |
|---|---|---|
| 실제 메일 공급자 연결·실발송 | HOLD | 공급자·발신 주소·SPF/DKIM, 멱등 키 지원(D5) |
| 템플릿 승인 | HOLD | PM(+법무: 마케팅·정책 변경) |
| outbox 표 정식 migration·Staging 적용 | migration 0005 작성 / 적용 HOLD | 운영·Staging 적용은 별도 PM 승인 후 수동 |
| 신규 동의 코드 3개 Seed | HOLD | T95 §10-4 (시험은 일회용 DB에만 삽입) |
| worker 실행 스케줄·CLI | 미구현 | 운영 방식 결정 후 (T51 worker 방식 재사용 예정) |
| 비밀번호 재설정을 이 모듈로 이전 | 안 함 | D2 — 비밀 변수 암호화 저장 방식이 승인되면 재검토 |
| 보안 알림 실패 운영 경보 | 로그(error)만 | T85 관리자 화면 연계는 별도 |
| 알림함(in_app) 읽음 상태 | 미구현 | 알림함 API 계약 필요 (T97은 Mock) |

## 6. 위험

- 공급자가 멱등 키를 지원하지 않으면 worker 중단 시 중복 발송 가능(D5).
- 조용한 시간이 KST 고정이라 해외 사용자에게 부정확(D6).
- 미승인 계약(T95) 기반이라 계약 변경 시 `SPECS`와 시험을 함께 고쳐야 함 — 시험이 표 불일치를 잡습니다.
