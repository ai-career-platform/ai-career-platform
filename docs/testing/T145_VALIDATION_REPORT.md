# T145 검증 보고서 — 백그라운드 작업·이벤트 재처리 통합 계약

## 1. 작업 목적
수집·알림·LLM 비동기 작업이 공통으로 따를 규칙을 정합니다.
- 상태, 멱등성, 재시도 한도·백오프
- 취소, dead-letter, 중복 Worker
- 이력, correlation id

이 규칙을 작은 라이브러리와 시험으로 고정합니다.

## 2. 기존 구현·PR 재사용
| 기존 | 재사용 방식 |
|---|---|
| T64 `run_state.py`, `run_claims.py`, `offline_recovery.py` | 불변 전이표, 중복 실행 거부, 일시·영구 오류 구분을 일반화했습니다(수정 없음). |
| T96 `notifications.py`(#198) | outbox·lease·지수 백오프·dedupe 규칙을 `KINDS["notification.deliver"]`로 옮겼습니다(수정 없음). |
| T112 `request_id`(#208) | 안전 형식 `[A-Za-z0-9._-]{8,64}`를 그대로 correlation id에 씁니다. |

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- HEAD_SHA: PR 댓글에 기록합니다.

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `backend/app/services/background_jobs.py` | 상태 머신, `KINDS` 정책, 결정적 백오프, `JobRunner`, 취소·replay, 메모리 저장소 |
| `backend/app/repositories/background_jobs_pg.py` | PostgreSQL 저장소(`FOR UPDATE SKIP LOCKED`, fencing 조건부 저장, append-only 이력) |
| `database/proposed/T145_background_jobs.sql` | 제안 DDL. **정식 migration 아님** |
| `backend/tests/test_t145_background_jobs.py` | 메모리·PG 매개변수화 시험 |
| `docs/architecture/BACKGROUND_JOB_CONTRACT.md` | 계약 문서 |

`config.py`, `main.py`, `env_contract.py`, `.env.example`, `database/migrations`는 변경하지 않았습니다. 라우터·Timer도 없습니다.

## 5. 선행조건
| 선행 | 상태 |
|---|---|
| T64 스케줄러·실행 관리 | MERGED |
| T96 알림 발송 모듈 | MERGED(PARTIAL, 공급자 기본 비활성) |
| T112 관측 | MERGED |
| **T110 LLM 비동기** | **NOT_STARTED**. `llm.*` 유형은 계약만 있고 enqueue하면 `ContractOnly`로 거부합니다. |

## 6. 실제 실행 명령
```bash
cd backend
PYTHONUTF8=1 T145_ADMIN_URL=postgresql://<admin>@127.0.0.1:55496/postgres \
  python -m pytest -q tests/test_t145_background_jobs.py
# 전체(일회용 PG, 공유 잠금 아래)
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=... T145_ADMIN_URL=... python -m pytest -q
```

T145 PG 시험은 `t145_jobs_<hex>` 일회용 DB를 만들고, 끝나면 `DROP DATABASE ... WITH (FORCE)`로 지웁니다.

## 7. 정상·오류·권한 검증 (35 passed, SKIP 0)
| 시나리오 | 메모리 | PostgreSQL 18.6 |
|---|---|---|
| 정상 완료, 이력, correlation id 전파, 로그에 payload 없음 | PASS | PASS |
| 중복 메시지·완료 뒤 재전송 → handler 1회 | PASS | PASS |
| 재시도 백오프(대기 1초 전 미실행, 도래 시 실행) → 한도 도달 시 dead_letter | PASS | PASS |
| 차단·영구 오류(VALIDATION_FAILED, HTTP_403, CAPTCHA, robots) → 1회 만에 dead_letter | PASS | PASS |
| 알 수 없는 예외 → 재시도, 예외 메시지 미저장 | PASS | PASS |
| 취소: queued 즉시, running 협조적 취소, 성공 후 취소 요청, 종료 상태 무시 | PASS | PASS |
| lease 만료 회수(attempt+1, token+1), 옛 Worker 늦은 보고 거부(LeaseLost) | PASS | PASS |
| Runner가 lease를 잃으면 덮어쓰지 않고 lease_lost로 집계 | PASS | PASS |
| 마지막 시도에서 lease 만료 → dead_letter | PASS | PASS |
| dead_letter 운영자 replay, 두 번째 replay 거부 | PASS | PASS |
| **Worker 4개 동시 claim → 24개 작업이 각각 1회** | PASS | PASS |
| handler 없는 유형은 claim 안 함 | PASS | PASS |
| 이력 UPDATE·DELETE 거부, 멱등 UNIQUE, lease CHECK | — | PASS |
| 전이표·종료 상태, LLM 계약 전용, 입력 검증(키·payload·naive 시각) | PASS | — |
| 백오프: 지수·상한·지터 범위·결정성·작업별 분산 | PASS | — |
| correlation id: T112 형식 그대로 이어 쓰기, 위험 값은 새로 발급 | PASS | — |

변이 확인: PG claim에서 `FOR UPDATE SKIP LOCKED`를 지우면 `test_competing_workers_claim_each_job_once[postgres]`가 **실패**했습니다. 확인 뒤 원복했습니다.

## 8. PostgreSQL / Mock / 실제 API 구분
| 항목 | 값 |
|---|---|
| UNIT_TESTS | PASS |
| POSTGRESQL_TESTS | PASS(로컬 일회용 PG 18.6). CI는 `T145_ADMIN_URL`이 없어 PG 매개변수를 SKIP합니다. |
| MOCK_VALIDATION | PASS(메모리 저장소, 합성 handler) |
| REAL_API_VALIDATION | NOT_RUN(HTTP API 없음) |
| STAGING_VALIDATION | NOT_RUN |
| 실제 Worker·Timer | 활성화 0건 |

전체 Backend 결과(일회용 PG 포함, Windows): **1675 passed, 101 skipped, 1 failed, 31 errors**.
- 실패·오류 32건은 `tests/test_documents.py`·`tests/security/test_security_upload.py`입니다.
- Windows에 `os.O_DIRECTORY`가 없어 생기는 사전 실패이며, main `822fa16`에서도 같은 1 failed / 31 errors입니다. Linux CI에서는 통과합니다.

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- 제안 DDL의 정식 migration 여부: T115 게이트, PM 승인
- 기존 T64 실행 기록·T96 outbox를 통합할지, 계약만 맞출지
- dead_letter 보존·정리 정책(append-only 이력과 CASCADE 충돌)
- replay 권한과 T83 감사 이벤트 연결
- T110 미착수: LLM 정책값 미확정

## 11. 후속 작업
1. 승인 뒤 T96 `NotificationWorker`·T154 fixture worker를 `JobRunner` 계약으로 옮기기(기존 시험 유지)
2. 운영 관리자 replay·cancel API(T155 관리자 권한 재사용)
3. 지표: 상태별 작업 수·dead_letter 경보(T113 규칙 추가)
