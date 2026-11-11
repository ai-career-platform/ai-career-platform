# T149 검증 보고서 — 비용·용량 계획·복구 우선순위

## 1. 작업 목적
DB·스토리지·로그·백업·AI 비용의 용량과 비용을 측정·추정하고, RTO/RPO와 복구 우선순위, 경보 기준을 제안합니다.

## 2. 기존 구현·PR 재사용
- 기존 T149 PR·브랜치 없음(신규).
- 재사용
  - T10 Seed
  - T147 합성 데이터 공장(`database/fixtures/synth_factory.py`, 그대로 실행)
  - T114 백업 옵션과 보존 기본값(일 7·주 4·월 3)
  - T119 loopback 전용·읽기 전용 측정 방식과 `COST-AI-BUDGET` 점검
  - T112 접근 로그 형식(한 줄 크기 실측)
- 기존 파일은 수정하지 않았습니다(새 파일만).

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- HEAD_SHA: PR 댓글에 기록

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `scripts/ops/t149_capacity.py` | `measure` / `project` / `check` |
| `scripts/ops/t149_activity_rows.sql` | 합성 활동 행(일회용 DB 이름 가드) |
| `docs/ops/capacity/t149_measured_local.json` | 4개 규모 실측 + 복원 훈련 |
| `docs/ops/capacity/t149_assumptions.json` | 가정·제안값(모두 basis·note 있음) |
| `docs/ops/capacity/t149_projection.json` | 3개 시나리오 12개월 예측 |
| `docs/ops/CAPACITY_COST_PLAN.md` | 계획 문서 |
| `backend/tests/test_t149_capacity.py` | 21건(PG 2건 포함) |

## 5. 선행조건
| 일감 | 상태 | 영향 |
|---|---|---|
| T112 관측 | main 병합 | 로그 한 줄 크기 실측에 사용 |
| T114 백업 | main 병합 | 덤프 옵션·보존 개수 재사용 |
| T119 점검표 | main 병합 | AI 예산 점검 연결 |
| **T110 AI 운영** | **NOT_STARTED** | AI 사용량·단가 실측이 없어 전부 추정 |

## 6. 실제 실행 명령
- 측정 DB 구성: `CAPACITY_COST_PLAN.md` §7 명령을 그대로 썼습니다(PostgreSQL 18.6 로컬 일회용 클러스터).
- 측정: `t149_capacity.py measure --dump`를 s0~s3에 실행했습니다.
- 복원 훈련: `pg_dump -Fc` → `pg_restore`를 3회 했습니다.
- 예측·대조: `project --out …`, `check` → `T149_CAPACITY_CHECK=PASS`
- 시험: `pytest tests/test_t149_capacity.py`
  - `T16_ISOLATED_DB_TEST=YES`를 켜고, 공용 DB 잠금(`pglock.sh`) 아래에서 실행했습니다.

측정 DB `t149_local_s0~s3`·`t149_local_restore`와 덤프는 삭제했습니다.

## 7. 정상·오류·권한 검증
| 구분 | 내용 | 결과 |
|---|---|---|
| 근거 표시 | 가정 26개 모두 basis(measured/estimated/proposed)·note | PASS |
| AI 비용 | AI 항목은 전부 `estimated`, "견적 아님"·T110 표기 | PASS |
| 잘못된 가정 | basis 없음·잘못된 basis·note 없음·음수·NaN·bool·시작>목표 사용자 → 거부 | PASS(7건) |
| 결정성 | 같은 입력 두 번 → 같은 결과, 저장된 예측 JSON과 일치 | PASS |
| 단조성 | 사용자 증가 시 DB·문서·로그·백업·AI 증가, 원본 HTML은 불변 | PASS |
| 손 계산 | AI·원본 HTML·문서·로그·백업·필요 디스크 수식 재계산 | PASS |
| 문서 ↔ 계산 | 문서 표 숫자 = 계산. 숫자를 바꾼 문서는 검출 | PASS |
| 원격 거부 | loopback이 아닌 주소 측정 거부 | PASS |
| 읽기 전용 측정 | 일회용 PG에서 측정 전후 행 수 동일, 51개 표 | PASS(PG) |
| DB 가드 | 활동 SQL은 `t149_local_*`가 아닌 DB에서 중단 | PASS(PG) |

## 8. PostgreSQL / Mock / 실제 구분
| 항목 | 결과 |
|---|---|
| UNIT_TESTS | PASS(19건, DB 없음) |
| POSTGRESQL_TESTS | PASS(2건, 일회용 PG 18.6) + 로컬 실측 4개 규모·복원 3회 |
| FRONTEND_TESTS / BROWSER_E2E | NOT_RUN(해당 없음) |
| MOCK_VALIDATION | 해당 없음 |
| REAL_API_VALIDATION | NOT_RUN |
| STAGING_VALIDATION | **NOT_RUN** — Staging 크기·디스크 실측은 접속 승인 필요 |

**실측은 합성 데이터 기준입니다.** 실제 데이터의 행 크기·압축률·HTML 크기는 다를 수 있습니다.

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- PM 결정 필요
  - 보존 기간(행동 이벤트·세션·원본 HTML·로그·백업 개수)
  - RTO/RPO
  - AI 예산
- T110 미착수: AI 비용이 계속 추정입니다.
- 실사이트 수집 HOLD: HTML 쪽 크기가 추정입니다.
- Staging 실측 승인

## 11. 후속 작업
- 승인 후 Staging 읽기 전용 `measure`와 실제 크기 복원 훈련
- 디스크·DB 증가율 경보를 T113 규칙에 추가
- 행동 이벤트 보존·집계 정책 수립
