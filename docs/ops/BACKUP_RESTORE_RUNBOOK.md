# DB 백업 정기화·복원 검증 Runbook (T114)

> 상태: **PROPOSED**. 도구와 시험은 이 PR에 들어 있습니다.
> - 실제 스케줄 등록, Staging·운영 백업, 업로드, 보존 파일 삭제는 **하지 않았습니다**.
> - 검증은 로컬 일회용 PostgreSQL 18.6(루프백)과 합성 데이터로만 했습니다.
> - 기존 T90 훈련 스크립트(`database/tests/t90_backup_restore_drill.py`)의 지문 함수를 재사용합니다.

## 1. 도구 `database/backup/t114_backup.py`

| 명령 | 하는 일 | 실패 판정 |
|---|---|---|
| `backup --db D --out-dir O --label L [--approval A]` | `pg_dump -Fc --no-owner --no-privileges`로 `L_D_<UTC>.dump`를 만들고 `.manifest.json`을 남깁니다. manifest에는 sha256, 크기, 목차 수, 서버·pg_dump 버전, 적용된 migration 목록, **표별 행 수·md5와 객체 수 지문**이 들어가고, 행 데이터는 넣지 않습니다 | 원격 호스트, 승인 기록 없는 비훈련 DB → 거부(exit 3) |
| `verify --manifest M` | sha256 → `pg_restore --list` 목차 수 → **새 `t114_verify_*` DB**에 복원 → 지문·객체·migration 비교 → DB 삭제(실패해도 삭제) | 형식·파일·체크섬·목차·복원·지문 불일치 → exit 1 |
| `retention-plan --dir O` | 일 7·주 4·월 3 규칙으로 남길 것과 만료할 것을 **계산만** 합니다 | — (삭제 기능 없음) |
| `freshness --dir O --rpo-hours 24` | 최신 백업 나이가 RPO를 넘거나 백업이 없으면 경보 | exit 2 |

환경변수 `T114_ADMIN_URL`(루프백만 허용)과 `PG_BIN`(pg_dump·pg_restore 경로)을 씁니다.

## 2. 정기화 절차 (제안, 승인 후)

```
매일 02:30 KST  backup(Staging, 승인 기록) → 같은 호스트의 비공개 백업 디렉터리(0700)
매일 03:00 KST  verify(최신 manifest, 루프백 일회용 DB) → 결과 JSON 보관
매시           freshness(RPO 24h) → 경보(T113 A-BACKUP-STALE)
매주 일요일     retention-plan → 운영자가 계획을 확인하고 수동 삭제(자동 삭제 없음)
```

- 스케줄러는 기존 `poc/staging/automation`의 systemd timer 방식을 따르는 것을 제안합니다. **이번에 timer를 만들거나 등록하지 않았습니다.** 운영 변경이므로 PM 승인이 필요합니다.
- 복원 검증은 **같은 서버의 별도 일회용 DB**에서만 합니다. 운영 DB·볼륨에는 덮어쓰지 않습니다.

## 3. 백업 권한 (최소 권한)

| 역할 | 권한 | 검증 |
|---|---|---|
| `t114_backup_ro`(시험용 이름, 운영 이름은 승인 시 결정) | `LOGIN` + `pg_read_all_data` | 격리 PG에서 pg_dump 성공, `INSERT`·`DELETE`는 `InsufficientPrivilege` |
| 복원 검증 | DB 생성 권한이 있는 관리 계정(루프백) | 복원은 새 DB에만 |

- 앱 계정(`career_app`)이나 PostgreSQL 관리자 계정으로 정기 백업을 돌리지 않는 것을 제안합니다.
- Staging에 역할을 만드는 일은 **공유 DB 변경이라 HOLD**입니다.

## 4. RPO/RTO

| 항목 | 실측(로컬 합성 데이터) | 제안 목표 | 비고 |
|---|---|---|---|
| 백업 시간 | 0.303초 (51표·2,058행, 202 KB) | — | `docs/ops/T114_BACKUP_DRILL_RESULT.json` |
| 복원 시간(RTO 중 DB 부분) | 0.391초 | 전체 RTO 1시간 | 실데이터 크기에서는 미측정 |
| RPO | — | 24시간(일 1회) | PoC·비상업 기준. 더 짧게 하려면 WAL 보관(PITR)이 필요하며 범위 밖 |

**실측값은 합성 데이터 기준입니다.** Staging 데이터 크기·디스크에서 다시 재야 하며, 그 측정은 HOLD입니다(접속 승인 필요).

## 5. 암호화·보관

- **암호화는 미구현(NOT_RUN)** 입니다. 저장소 의존성에 암호화 라이브러리가 없고, 서버의 `age`나 `gpg` 사용 여부가 정해지지 않았습니다.
  - 제안: 덤프와 manifest를 `age` 공개키로 암호화합니다. 개인키는 서버 밖(PM 보관)에 두고, 복원 검증 시에만 씁니다.
- 외부 업로드(클라우드 저장소)는 **하지 않습니다.** 미승인 백업 업로드는 금지되어 있습니다(T114 §5).
- manifest에는 행 데이터 없이 해시와 개수만 들어 있습니다. 합성 이메일 문자열이 없음을 시험으로 확인했습니다.

## 6. 실패 대응

| 경보·실패 | 의미 | 조치 |
|---|---|---|
| backup exit 3 | 원격 호스트, 또는 승인 없는 대상 | 설정 확인. 우회 금지 |
| verify `sha256 mismatch` | 파일 손상·변조 | 이전 백업으로 verify, 저장 매체 점검 |
| verify `pg_restore failed`·`table of contents` | 덤프 손상(체크섬을 다시 맞춘 손상 포함) | 이전 백업으로 verify, 다음 백업을 즉시 실행 |
| verify `differs` | 복원 내용이 백업 시점 지문과 다름 | 백업을 무효로 표시, 원인 조사 |
| freshness exit 2 | RPO 초과·백업 없음 | 스케줄러·디스크 확인 후 수동 백업(T113) |
