# T113 검증 보고서 — 장애 대응·알림·운영 Runbook

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 경보는 Mock 채널로만 검증했습니다. 운영 알림 채널·수신자는 승인 전입니다.
> - Staging 장애 주입은 하지 않았습니다.
> **스택**: main `ab56765` → T112 #208 → 이 PR

## 1. 목적
DB 연결·API 5xx·AI 과금·외부 공급자 장애에 대한 알림 조건과 조치 절차를 정합니다. 관측 → 판단 → 복구 → 보고 흐름을 재현합니다.

## 2. 선행 일감
- T30·T90 운영·릴리스 문서: main
- T112 관측 계약: **#208 미병합(스택)**. `RequestMetrics`, request_id, 로그 필드를 씁니다.
- T114 백업 신선도: #211(미병합). 값 형식만 맞추고 코드 의존은 없습니다.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `scripts/ops/t113_alerting.py` (신규) | 규칙 평가, 연속 N회 탐지, 30분 중복 억제, 원인 억제(inhibit), 15분 미확인 에스컬레이션, RESOLVED, 사후 보고 요약, 결정적 모의 훈련 |
| `docs/ops/alerting/alert_rules.yaml` (신규) | 경보 8개(DB·API 다운, 5xx, 지연, AI 공급자, 예산 80·100%, 백업 지연) — PROPOSED 임계값 |
| `docs/ops/INCIDENT_RUNBOOK.md` (신규) | 공통 절차, 장애별 R1~R5, 훈련 결과, 사후 보고 양식 |
| `docs/ops/T113_REHEARSAL_EVIDENCE.json` (신규) | 훈련 타임라인·보고 |
| `backend/tests/test_t113_alerting.py` (신규) | 27건 |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12 · 일회용 PostgreSQL 18.6)

| 범주 | 시험 | 결과 |
|---|---|---|
| 규칙 | 8개 규칙의 Runbook 절 연결, T112 관측 필드만 사용 | PASS |
| 흔들림 | 1회 실패는 무시(연속 2회 필요) | PASS |
| **DB 장애** | 1회 FIRING, 억제, 15분 미확인 → 2차 에스컬레이션, 복구 → RESOLVED(1차 알림은 FIRING·RESOLVED 2개뿐) | PASS |
| 확인(ACK) | 확인한 critical은 에스컬레이션하지 않음 | PASS |
| 장기 장애 | 30분 뒤 REPEAT 1회 | PASS |
| **원인 억제** | DB 장애 중 5xx는 INHIBITED, DB 복구 후에도 5xx가 계속되면 FIRING | PASS |
| 경계값 14종 | 표본 부족, 5% 경계, 지연, 공급자 오류 4/5, 예산 79.8%/80%/100%, 예산 미설정, 백업 24시간/24.5시간/없음 | PASS |
| p95 계산 | T112 지연 구간에서 p95 상한 | PASS |
| 메시지 | Runbook 링크 포함, 정해진 필드만(비밀값 없음) | PASS |
| **실제 앱: DB 장애** | 닫힌 포트 → `/health/db` 503 `DEPENDENCY_UNAVAILABLE`, A-DB-DOWN 발생, A-API-DOWN 미발생 | PASS |
| **실제 앱: DB 복구** | 일회용 PostgreSQL → 200, RESOLVED | PASS(로컬, CI는 Postgres 서비스) |
| **실제 앱: 5xx** | `RequestMetrics` 스냅샷 → A-API-5XX 발생 | PASS |
| 훈련 재현 | 커밋한 증빙 = 새로 돌린 결과(결정적), 장애 6종 탐지·해소 | PASS |

- `test_t113_alerting.py` **27 passed**, T112 시험 16건 함께 통과(합계 43)
- 실제 Staging 장애 주입과 운영 채널 전송은 **NOT_RUN**입니다.

## 5. 미승인·후속
1. 임계값 확정: T119 실측 기준선 이후
2. 알림 채널·수신자·당번표(PM)
3. AI 월 예산 금액(PM)
4. 평가 엔진 상시 실행(스케줄러)과 수집기 연결: 운영 변경이라 승인이 필요합니다.
