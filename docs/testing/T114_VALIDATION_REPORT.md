# T114 검증 보고서 — DB 백업 정기화·복원 검증 자동화

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 격리 PostgreSQL에서 실제 백업·복원·무결성 검증을 PASS했습니다.
> - Staging 백업, 스케줄 등록, 암호화, 업로드는 미실행입니다.

## 1. 목적
승인된 DB 백업 주기·보관·격리 복원 검증을 자동화합니다(암호화는 제안).

## 2. 선행 일감

| 일감 | 상태 | 사용 |
|---|---|---|
| T08 migration 러너 | 병합 | `career_migration.schema_migrations`(manifest에 migration 목록) |
| T12 DB | 병합 | 스키마 |
| T90 릴리스 | 병합 | `t90_backup_restore_drill.py`의 `fingerprint`·`seed_source` 재사용 |
| T111 환경 계약 | **PR #207 미병합** | 이 도구는 Backend 앱 설정을 쓰지 않습니다(`T114_ADMIN_URL`은 운영 도구 변수). 코드 의존 없음 |

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `database/backup/t114_backup.py` (신규) | backup / verify / retention-plan / freshness |
| `backend/tests/test_t114_backup.py` (신규) | 단위 20 + 격리 PG 6 = 26건 |
| `docs/ops/BACKUP_RESTORE_RUNBOOK.md` (신규) | 도구, 정기화 제안, 권한, RPO/RTO, 암호화·보관, 실패 대응 |
| `docs/ops/T114_BACKUP_DRILL_RESULT.json` (신규) | CLI 실측 결과 |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12 · PostgreSQL 18.6 일회용 클러스터, 루프백 55496)

| 범주 | 시험 | 결과 |
|---|---|---|
| 보존 계획 | 120일치에서 최근 7일 + 주·월 대표만 유지, 같은 날 여러 개는 최신 1개, 미래 시각 백업은 지우지 않음, CLI가 파일을 지우지 않음 | PASS (4) |
| RPO 경보 | 백업 없음·24.5시간 → 경보, 24시간·1시간 → 정상, CLI exit 2 | PASS (5) |
| 안전 거부 | 원격 호스트 3종(문서용 IP, compose 서비스명, 도메인) 거부, 승인 없는 비훈련 DB 거부(빈 값·공백 포함), CLI exit 3 | PASS (7) |
| 변조 차단(복원 전) | 알 수 없는 형식, 체크섬 불일치, 덤프 없음, 덤프 바이트 변경 | PASS (4) |
| **실제 백업 → 격리 복원** | 51표·2,058행 지문·객체·migration 일치, manifest에 행 데이터 없음 | PASS |
| 손상 덤프 | 중간 4 KB를 0으로 바꾸고 체크섬을 다시 맞춤 → 복원 단계에서 FAIL, 검증 DB 남지 않음 | PASS |
| 잘린 덤프 | 1/3로 자름 → FAIL | PASS |
| 지문 불일치 | manifest 행 수 +1 → FAIL | PASS |
| **백업 권한** | `pg_read_all_data` 역할로 덤프 성공, INSERT·DELETE는 권한 거부 | PASS |
| 승인 기록 | 비훈련 DB 백업 시 manifest에 승인 기록 | PASS |

- **26 passed**(PG 통합 6건 포함).
- CI에서는 `T114_ADMIN_URL`이 없어 PG 통합 6건은 skip되고 단위 20건만 실행됩니다. Runner의 pg_dump 버전이 서버보다 낮아도 skip합니다.
- CLI 실측(`docs/ops/T114_BACKUP_DRILL_RESULT.json`):
  - 백업 0.303초 / 202 KB / 목차 321개
  - 복원 0.391초, verdict PASS
  - freshness: 정상 → `alert=false`, 이틀 뒤 시각 → `alert=true`
- 전체 Backend 회귀: 앱 코드 변경이 없습니다. CI에서 실행합니다.

## 5. 한계
- 실측은 합성 데이터 기준이라 Staging 실제 크기의 RTO는 모릅니다.
- 원본 DB를 migration 러너가 아니라 SQL 직접 적용으로 만들어 manifest의 migration 목록이 비어 있습니다. 러너로 만든 DB에서는 목록이 채워지고 비교됩니다(코드 경로는 같습니다).
- 암호화: NOT_RUN

## 6. 미승인·후속
1. 스케줄(systemd timer)·백업 디렉터리·보존 규칙 승인
2. Staging 읽기 전용 백업 역할 생성(공유 DB 변경, HOLD)
3. 암호화 방식(age/gpg)과 키 보관 결정
4. Staging 실데이터 크기에서 RTO 재측정
