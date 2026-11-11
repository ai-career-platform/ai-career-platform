# T119 검증 보고서 — 데이터 품질·AI 편차·서비스 SLO 주기 점검

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 점검 도구·임계값·플레이북을 넣었습니다.
> - **실측 기준선이 없어** 임계값은 모두 candidate·synthetic·none입니다.
> - AI 품질은 T105 미착수라 `not_measured`입니다. Staging 실행은 HOLD입니다.

## 1. 선행 일감

| 일감 | 상태 | 사용 |
|---|---|---|
| T65 시장 지표 | 병합 | 이번 점검 범위 밖(공고 표 중심) |
| T73 행동 데이터 품질 | 병합 | 범위 밖. 후속 항목 후보 |
| **T105 추천 평가** | **NOT_STARTED** | AI 품질 not_measured |
| T112 관측 | #208 미병합 | 지표 스냅샷 형식(코드 의존 없음) |
| T88 성능 기준선 | 병합 | p95 < 100 ms를 candidate로 |

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `scripts/ops/t119_scorecard.py` (신규) | 읽기 전용 측정(누락률·중복률·만료 게시·신선도·분포·월 AI 비용), PSI, SLO(T112 스냅샷), 판정, breach면 exit 2 |
| `docs/ops/quality/t119_thresholds.yaml` (신규) | 점검 12개(주기·책임 역할·임계값·근거) |
| `docs/ops/QUALITY_SCORECARD.md` (신규) | 항목·주기·책임, 위반 시 조치, 재학습·롤백 제안 절차, 합성 실행 결과, 결정 사항 |
| `docs/ops/quality/T119_SCORECARD_SYNTHETIC_RUN1.json`, `RUN2.json` (신규) | 합성 실행 결과 |
| `backend/tests/test_t119_scorecard.py` (신규) | 16건 |

## 3. 시험 결과 (로컬 Windows 11 · Python 3.12 · PostgreSQL 18.6 일회용)

| 시험 | 결과 |
|---|---|
| PSI: 같은 분포 0, 작은 변화 < 0.1 < 0.25 < 큰 변화, 새 범주 처리 | PASS |
| 판정 경계(위·아래 방향 7종), 측정값 없음 → not_measured, 임계값 없음 → no_threshold | PASS |
| 지표·예산이 없으면 SLO·비용·AI·분포는 not_measured(ok로 세지 않음) | PASS |
| T112 스냅샷 → 가용성 0.99(warn), p95 100 ms(ok) | PASS |
| 임계값 근거 표시: `measured` 0개, 근거 없는 항목은 설명 필수, AI 품질 임계값 없음 | PASS |
| 커밋한 합성 실행: "synthetic" 표시, RUN2 PSI breach, AI not_measured | PASS |
| 원격 DB 거부 | PASS |
| **일회용 PG 실측**: 중복·만료 게시 행 추가가 비율에 반영, 측정 전후 행 수 동일(읽기 전용), 누락률 0~1, 신선도 계산 | PASS |

**16 passed.** CI에서는 Postgres 서비스로 실측 시험도 실행됩니다.

## 4. 합성 실행
- RUN1: ok 9 · breach 1(신선도) · not_measured 2
- RUN2: 분포를 바꾼 뒤 **PSI 0.69 breach**
- 실행에 쓴 일회용 DB는 삭제했습니다.

## 5. 미승인·후속
주기·책임자·스케줄 등록, SLO 목표·AI 예산, T105 착수, Staging 읽기 전용 실행 방법(HOLD)
