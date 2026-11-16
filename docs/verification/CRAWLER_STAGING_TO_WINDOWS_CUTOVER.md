# Ubuntu Staging 크롤러·GCP Sync 중지 및 Windows 전환 (AI_CAREER_CRAWLER_STAGING_TO_WINDOWS_CUTOVER, 2026-11-16)

**결론: PM 이 중지를 승인했지만, 이 PC 에서는 Staging 에 접근할 수 없어 실제 중지는 수행하지 못했습니다 (BLOCKED).**

## 1. 접속 상태

| 항목 | 값 |
|---|---|
| Staging 에서 실행된 명령 | 0 |
| 이 PC 의 네트워크 | Wi-Fi `10.2.17.x/23`. Staging 은 `10.2.10.x`. 17:13 실패 때와 동일 |
| SSH 설정 | 포트 22, 키 없음, VPN·ssh_config 없음 |
| 판단 | 17:13 의 TCP 22 시간 초과와 같은 조건이므로 지시대로 다시 시도하지 않았습니다 |
| 필요한 경로 | Staging 서버 콘솔, 또는 Staging 에 접근 가능한 기존 관리 PC 에서 담당자(`kant`)가 실행 |

## 2. 준비한 실행 도구 (승인 범위만 수행)

- **스크립트:** `poc/staging/automation/safety/staging_cutover_stop.sh`
  - 커밋 `e4c6fa6139360ad57fc39342bb2b7f5a792d73e0`
  - SHA-256 `7d8a76a6bb1ee273fae11c17c9a5ce5b78fa571bdcb3fa8219136be215e3df98` (LF)

| 모드 | 동작 |
|---|---|
| `plan` | 읽기 전용. 바꿀 crontab 줄과 timer, 제외되는 timer, 실행 중 프로세스, 마지막 Sync, 26시간 기준 시각을 보여 줍니다 |
| `apply --approval-ref <참조>` | 아래 1–5 단계를 순서대로 수행합니다 |
| `verify` | 읽기 전용 상태 확인 |
| `rollback <백업> --yes` | 체크섬 검증 후 crontab 과 timer 상태를 정확히 복원합니다 |

**`apply` 의 단계:**
1. 백업: `~/aicp-cutover-backup-<UTC>`, 권한 700.
   - 대상: crontab, timer 상태, unit 내용, 배포 commit, 컨테이너 상태, `gcp-sync.env` **키 이름만**, 마지막 Sync 기록, 프로세스. SHA256SUMS 를 함께 만듭니다.
   - 백업 검증에 실패하면 아무것도 바꾸지 않습니다.
2. 크롤링·Sync 가 실행 중이면 완료까지 기다립니다(기본 30분). **강제 종료하지 않으며**, 시간을 넘기면 변경 없이 중단합니다.
3. crontab 에서 크롤러·GCP Sync 줄만 `# AICP-CUTOVER-DISABLED <시각>` 으로 주석 처리합니다.
   - 대상 패턴: `run_gcp_sync.sh`, `crawler.jobs`, `night_crawl`, `dispatcher`, `import_jobkorea`, `harvest`
   - 그 외 줄은 바이트 단위로 유지되며, 줄 수가 같은지 검증합니다.
4. timer: `ai-career-*`·`t61*` 중 crawler, night, t15x, harvest, gcp 에 해당하는 것만 `sudo systemctl disable --now` 합니다.
   - **`ai-career-staging-deploy.timer`(배포), docker, backend, PostgreSQL 은 건드리지 않습니다.**
5. 검증 출력.
   - 비밀값이 출력에 나오지 않도록 마스킹합니다. crontab 백업 사본은 서버의 700 디렉터리에만 둡니다.

**이 PC 의 시험 결과 (Git Bash, crontab·systemctl·sudo·pgrep 모의, 실제 Ubuntu 아님):**

| 시험 | 결과 |
|---|---|
| apply | 활성 대상 2줄만 주석 처리. 무관한 backup 줄과 이미 주석인 줄은 그대로. dispatch timer 만 disable, deploy timer 는 enabled 유지 |
| 재실행 | 변경 0 (멱등) |
| 실행 중 Sync 가 있을 때 | 변경 없이 중단 |
| 승인 참조 누락 | 거부 |
| rollback | crontab 과 timer 상태가 원본과 동일 |
| 백업 변조 후 rollback | 거부 |
| 출력의 webhook·비밀번호 | 0건 |
| 시험 중 고친 결함 | awk 정규식 이스케이프, SHA256SUMS 가 자기 자신을 포함하던 문제 |

## 3. 담당자 실행 절차 (Staging 서버, 사용자 kant)

```bash
set -eu; cd "$(mktemp -d /tmp/aicp-cutover-XXXX)"
curl -fsSL -o staging_cutover_stop.sh \
  https://raw.githubusercontent.com/ai-career-platform/ai-career-platform/e4c6fa6139360ad57fc39342bb2b7f5a792d73e0/poc/staging/automation/safety/staging_cutover_stop.sh
echo "7d8a76a6bb1ee273fae11c17c9a5ce5b78fa571bdcb3fa8219136be215e3df98  staging_cutover_stop.sh" | sha256sum -c -
bash staging_cutover_stop.sh plan | tee plan.txt          # 1) 읽기 전용: 대상 확인
bash staging_cutover_stop.sh apply --approval-ref "PM-CUTOVER-20261116" | tee apply.txt   # 2) 중지 (sudo 비밀번호 입력)
bash staging_cutover_stop.sh verify | tee verify.txt      # 3) 확인
```

1. **`plan` 확인:** 대상 crontab 줄과 timer 가 크롤러·GCP Sync 뿐인지 확인합니다. 예상과 다르면 `apply` 하지 않습니다.
2. **전달물:** `plan.txt`, `apply.txt`, `verify.txt` (마스킹됨). 백업 디렉터리 경로와 그 안의 `SHA256SUMS` 도 함께 전달합니다.
3. **다음 날 증거:** 다음 08:05 KST(23:05 UTC) 이후 `verify` 를 다시 실행해 `last_sync_record` 가 그대로인지 확인합니다. 새 Sync 가 실행되지 않았다는 증거입니다.

## 4. 26시간 조건

스케줄 중지만으로 충족되지 않습니다.
- `verify` 는 로그의 마지막 Sync 시각과 `windows_cutover_earliest_utc`(마지막 Sync + 26h)를 출력합니다.
- Windows 쪽 sync 는 실행 직전에 GCP `career.ingestion_runs` 로 다시 검사합니다. 26h 이전이면 `OTHER_SYNC_RECENT`, 실행 중이면 `OTHER_SYNC_RUNNING` 으로 거부됩니다.
- 마지막 실제 Sync 시각은 현재 **미확인**입니다. 서버 결과가 오면 기록합니다.

## 5. Windows PC 상태 (이 PC, 읽기 전용 확인)

| 항목 | 값 |
|---|---|
| main | `0edc175`. 실행 사본 트리 동일 |
| PostgreSQL | 18.7, 127.0.0.1:5432 실행 중 (`AICP-LocalPostgres` Running) |
| LIVE 공고 | Run `8e54090d` SUCCEEDED, HTTP 7, 공고 5건 보존 |
| 자동 실행 | `AICP-Crawler-Fixture` Disabled. LIVE·GCP 정기 스케줄 없음 (지시대로 활성화하지 않음) |
| GCP Sync 코드 | 출처 검증, 단일 writer, 26h, cutover evidence 포함(#372). `secrets\gcp-sync.env`·CA 없음 → `WINDOWS_GCP_SYNC_READY=NO` |

## 6. GCP 연결 준비 (변경 없음)

| 항목 | 상태 |
|---|---|
| CA | Staging 의 `gcp-sync/server-ca.pem`(공개 인증서)을 이 PC 의 `C:\dev\crawler-data\secrets\gcp-server-ca.pem` 으로 복사합니다. 비밀번호와 `gcp-sync.env` 는 복사하지 않습니다 |
| `career_sync` | Staging 점검 스크립트 5절의 `target_user_is_career_sync` 로 존재 여부를 확인합니다. 없으면 [CRAWLER_EXTERNAL_HANDOFFS.md](CRAWLER_EXTERNAL_HANDOFFS.md) B1·B2 절차 |
| 호스트명·네트워크 | 같은 문서 B3. 네트워크 변경은 별도 승인 |
| GCP 쓰기 승인 C | **NOT_GRANTED**. dry-run 준비까지만 합니다 |

## 7. 원상복구 절차 (준비만, 자동 실행하지 않음)

1. PM 의 복구 승인을 확인합니다.
2. Windows 쪽: LIVE·GCP 정기 작업이 없음을 확인합니다(현재도 없음). 수동 sync 를 실행하지 않습니다.
3. 중복 실행 확인: GCP `career.ingestion_runs` 에서 Windows(`"source":"local"`) 실행이 진행 중이 아닌지 봅니다.
4. Staging: `bash staging_cutover_stop.sh rollback ~/aicp-cutover-backup-<UTC> --yes`
   - 체크섬을 검증한 뒤 crontab 과 timer 를 원래 enabled/active 상태로 되돌립니다.
5. `verify` 로 crontab 줄과 timer 가 원래대로 돌아왔는지 확인합니다. 다음 08:05 실행 로그로 정상 실행을 확인합니다.
   - **주의:** Staging 에 #372 코드가 배포된 상태에서 Windows 가 cutover 실행을 한 번이라도 했다면, 그 뒤 Staging 실행은 코드상 `OTHER_SYNC_SOURCE_ACTIVE` 로 거부됩니다. 이 경우 Staging 쪽에도 cutover 확인값과 증거가 필요합니다.
