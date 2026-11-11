# T115 검증 보고서 — 환경별 DB Migration 안전 게이트

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 게이트·시험·CI 단계를 넣었습니다.
> - Staging 적용 절차는 승인 전이고, Staging에 접속하지 않았습니다.
> - 기존 러너는 수정하지 않았습니다.

## 1. 목적
개발 → 격리 CI → Staging 승인 적용으로 이어지는 DB 스키마 변경 절차를 자동 검증합니다.

## 2. 선행 일감

| 일감 | 상태 | 사용 |
|---|---|---|
| T08 러너·T09 0001·T12 | 병합 | `migrate.py` lint·승인 규칙·`APPROVAL_RE` 재사용 |
| T111 환경 계약 | #207 미병합 | 코드 의존 없음 |
| T114 백업 검증 | #211 미병합 | `preflight`가 T114 manifest·verify 결과 형식을 받음(코드 의존 없음) |

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `database/gate/t115_migration_gate.py` (신규) | `pr`(G1~G7), `preflight`(Staging 체크리스트, 적용 안 함) |
| `database/tests/test_t115_migration_gate.py` (신규) | 단위 13 + 일회용 PG 리허설 2 = 15건(unittest, 기존 러너 시험과 같은 형식) |
| `.github/workflows/db-migration-runner-test.yml` | PR에서 게이트 실행, T115 시험 실행(기존 단계 유지) |
| `docs/ops/MIGRATION_SAFETY_GATE.md` (신규) | 단계, 규칙, 체크리스트, 실패·복구, 결정 사항 |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12 · PostgreSQL 18.6 일회용)

| 범주 | 시험 | 결과 |
|---|---|---|
| G1 | 적용된 파일 수정·삭제 실패, 줄바꿈만 다르면 통과 | PASS |
| G2 | 다음 번호 통과, 빈칸·중복·base 이하 번호 실패 | PASS |
| G3 | 헤더 없음·승인 없는 DROP → 러너 lint 실패 전달 | PASS |
| G4 | 깨는 DDL 6종 헤더 없으면 실패, 헤더 있으면 통과. 추가형 4종은 통과. 주석 안의 헤더는 무시 | PASS |
| G5 | UPDATE·DELETE·INSERT…SELECT는 헤더 필요, 단순 INSERT 통과 | PASS |
| G6·G7 | 합성 저장소에서 앱 DDL·자동 apply 검출. 실제 저장소는 0건 | PASS |
| 실제 이력 | 현재 저장소 migration 3개가 게이트 통과. 0002·0003을 도입 커밋의 base와 비교해 다시 돌려도 0건 | PASS |
| preflight | 모두 충족 시 준비 완료. 9가지 실패(승인 없음·형식 오류, DB 불일치, 대기 없음, 백업 없음·26시간, 복원 FAIL, 다른 백업의 verify, staging 아님) 각각 차단 | PASS |
| **실패 원자성(일회용 PG)** | 중간 오류 migration → 전체 롤백, ledger `0001`만, 뒤 파일 미실행, 기존 데이터 유지 → 고친 뒤 0002·0003 적용 | PASS |
| **파괴적 migration 복원 리허설(일회용 PG)** | 50행 백업 → 승인된 DROP COLUMN 적용 → 새 DB에 복원 → 50행·컬럼 복구, ledger `0001` | PASS |

- **15 tests OK**(PG 포함). PG 변수가 없으면 13 OK / 2 skipped.
- CI 참고:
  - Runner의 pg_dump(16)가 서버(18.1)보다 낮으면 복원 리허설은 skip됩니다.
  - 원자성 시험은 CI Postgres에서 실행됩니다.
- **기존 러너 시험(`test_migration_runner.py`)은 로컬 Windows에서 4건 실패합니다.**
  - main 기준 트리에서도 같은 4건이 실패하므로 이번 변경과 무관하며, PASS로 세지 않았습니다.
  - Linux CI에서는 통과합니다.

## 5. 미승인·후속
1. G4·G5 헤더 형식과 Expand/Contract 규칙(PM)
2. Staging 적용 시간대, 백업 기준
3. `CONCURRENTLY` 인덱스의 러너 밖 절차(T99)
4. Staging 실제 사전점검·적용: HOLD
