# DB Migration 안전 게이트·배포 절차 (T115)

> 상태: **PROPOSED**. PR 게이트와 CI 단계는 이 PR에 들어 있습니다. Staging 적용 절차는 PM 승인 전입니다.
> - 기존 러너 `database/migrate.py`(T08)는 **수정하지 않았습니다.** 게이트는 러너의 lint와 승인 규칙을 그대로 불러 씁니다.
> - **migration 자동 적용을 Auto-CD에 연결하지 않습니다.** G7이 이를 검사합니다.

## 1. 단계

```
개발(로컬)       migrate.py lint / apply --target local (일회용 DB)
   ↓ PR
CI(격리)         [T08] lint + 일회용 PostgreSQL 적용 시험
                 [T115] PR 게이트 G1~G7 + 실패·복원 리허설 시험
   ↓ 병합(코드만 배포 — Auto-CD는 migration을 실행하지 않음)
Staging(수동)    T114 백업 → verify PASS → T115 preflight → 사람이 migrate.py apply --target staging
                 --approval <승인번호> --confirm-db <DB 이름>   (러너가 CI 실행·승인 누락·DB 불일치를 거부)
```

## 2. PR 게이트 규칙 (`database/gate/t115_migration_gate.py pr`)

| 규칙 | 검사 | 실패 시 |
|---|---|---|
| G1 | base에 있는(적용됐을 수 있는) migration 파일의 수정·삭제·이름 변경. 줄바꿈 차이는 무시 | 새 번호 파일로 고치기 |
| G2 | 새 번호 > base 최대 번호, 빈칸 없음, 중복 없음 | 병렬 PR 충돌 → rebase 후 번호 조정 |
| G3 | 러너 lint: 이름, `Purpose`·`Recovery` 헤더, 파괴적 SQL의 `Destructive-Approval`, 금지 구문 | 헤더·승인 추가 |
| G4 | **하위호환을 깨는 DDL**: 컬럼 삭제·이름 변경, 표 이름 변경, 형 변경, NOT NULL 추가, 기본값 없는 NOT NULL 컬럼, 표 삭제 | `-- Compatibility: contract <앱 배포 순서>` 헤더. Expand(추가) → 앱 배포 → Contract(제거) 순서 |
| G5 | 데이터 변경(UPDATE·DELETE·INSERT…SELECT) | `-- Data-Impact: <대상·예상 행 수·되돌리는 법>` 헤더 |
| G6 | 앱 코드(`backend/app`)가 DDL 문자열을 실행 | 스키마 변경은 migration으로만 |
| G7 | 워크플로·Staging 자동화가 `migrate.py apply` 실행 | 자동 배포와 migration 연결 금지 |

- 기존 체크섬 drift·순서 검사(`migrate.py verify`)와 Staging 가드(`guard_target`)는 그대로 씁니다.
- 스키마 스냅샷 비교는 기존 `t05-reference-schema-check` 워크플로가 담당합니다.

## 3. Staging 적용 전 체크리스트 (`preflight`, 적용하지 않음)

| 확인 | 기준 |
|---|---|
| 대상 | `--target staging` |
| 승인 번호 | Redmine·PR 승인 번호(러너와 같은 형식) |
| DB 이름 | `--confirm-db` = 접속한 DB |
| 대기 migration | `migrate.py status`의 PENDING 목록이 비어 있지 않음 |
| 백업 | T114 manifest가 24시간 이내 |
| 복원 검증 | **그 백업에 대한** T114 `verify` 결과 PASS |

하나라도 실패하면 중단합니다. 모두 통과해도 **적용은 사람이 러너로** 합니다.

## 4. 실패·복구

| 상황 | 동작(리허설로 확인) | 복구 |
|---|---|---|
| migration 실행 중 오류 | 파일 하나가 트랜잭션 하나라서 **전부 롤백**됩니다. 이력(ledger)은 그대로이고, 뒤 파일은 실행하지 않습니다 | 적용되지 않은 파일은 고쳐서 다시 적용합니다(forward fix) |
| 적용 후 문제(데이터 손실 등) | 되돌림(down) 스크립트는 없습니다(forward-only) | 수정 migration, 또는 **T114 백업을 새 DB에 복원 → 검증 → 승인 후 교체** |
| 적용된 파일 수정 | 러너 `verify`가 DRIFT로 거부하고, G1이 PR에서 거부 | 새 번호 파일 |

## 5. 결정 필요 (PM)

1. G4·G5 헤더 형식, Expand/Contract 운영 규칙
2. Staging 적용 시간대와 백업 기준 24시간
3. `CONCURRENTLY` 인덱스(T99 권장 인덱스)를 위한 러너 밖 절차. 러너는 금지하므로 수동 절차와 승인이 필요합니다
