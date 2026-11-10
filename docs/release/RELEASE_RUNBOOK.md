# T90 — 릴리스·복구·인수인계 Runbook

> 대상: 운영 담당자. 기존 구현(T30 CD, `deploy.py`, `migrate.py`)을 재사용하며 새 자동화는 없습니다.
> **실제 배포·DB 변경은 각 단계의 승인이 있을 때만** 진행합니다. 비밀번호·토큰·`.env` 내용은 기록하지 않습니다.

## 1. 구성 요약

| 요소 | 현재 | 근거 |
|---|---|---|
| 코드 → 이미지 | main push → CI → "Publish verified Staging release"가 SHA 태그 이미지를 GHCR에 올리고 `release.json`(SHA·digest·CI run)을 artifact로 남김 | `.github/workflows/staging-publish.yml` |
| 배포 | Staging 호스트의 Pull형 CD(`deploy.py`): 승인자·CI 재확인, digest 검증, **앞으로만 배포**(이전 SHA로 되돌리기 거부), 같은 SHA 재배포 방지, Health Gate 4경로 | `poc/staging/automation/deploy.py` |
| 상태 기록 | `.deploy-state/success.json`·`previous.json`, 실패 시 `hold.json` → 운영자 확인 전 다음 배포 중단 | 같음 |
| DB Migration | forward-only 실행기, checksum 원장 `career_migration.schema_migrations`, Staging은 승인·DB 확인 필요 | `database/migrate.py` |
| Staging DB | 원장 없음, 0002·0003 미적용 | PR #178 |

## 2. 릴리스 절차 (Gate 통과 후)

1. [FINAL_RELEASE_GATE.md](FINAL_RELEASE_GATE.md)가 GO이고 PM 승인 기록이 있는지 확인합니다.
2. main HEAD SHA, main CI run, 게시 run, `release.json`의 SHA·digest를 기록합니다(`gh run download <publish-run> -n verified-staging-release`).
3. **DB 먼저**: 백업 → 격리 복원 훈련 PASS → 승인된 Migration만 `migrate.py apply --target staging`(승인·DB 확인 옵션). 실패하면 중단합니다(§4).
4. CD가 새 manifest를 가져가 배포합니다. Health Gate(`/`, `/api/health`, `/api/version`, `/api/health/db`)를 확인합니다.
5. 사후 확인(읽기 전용):
   - `/api/version` = 기록한 SHA
   - `success.json`의 digest = manifest digest
   - DB 컨테이너·볼륨 식별자가 바뀌지 않음
6. 결과를 Gate 문서 판정 이력에 추가합니다.

## 3. 롤백 (애플리케이션)

CD는 **이전 SHA로의 역방향 배포를 거부**합니다(`NON_FORWARD_DEPLOYMENT`). 따라서:

| 방법 | 언제 | 절차 |
|---|---|---|
| **A. 되돌림 커밋으로 앞으로 배포 (기본)** | 대부분의 결함 | 문제 PR을 `git revert`한 PR → 리뷰·CI → 병합 → 새 SHA로 게시·배포. 기존 보호 규칙 그대로 |
| B. 수동 digest 고정 (긴급) | Health Gate 실패로 서비스 불가, A를 기다릴 수 없음 | **PM 승인 필수.** 운영자가 `previous.json`의 이전 digest로 Compose 서비스만 재기동. DB 볼륨·다른 프로젝트 리소스는 건드리지 않음. 이후 `hold.json`을 정리하고 A로 정상화 |

금지: `docker compose down -v`, 전역 prune, DB 자동 초기화, 보호 규칙 우회.

## 4. 롤백 (DB)

- Migration 실행기는 forward-only입니다. **down migration은 없습니다.**
- Migration 실패 시: 실행기가 트랜잭션을 되돌리고 원장에 남기지 않습니다. 원인을 고친 새 Migration으로 앞으로 진행합니다.
- 데이터 손상 시: §5 백업에서 **격리 복원 → 검증 → 승인 후 교체**합니다. 운영 DB에 직접 덮어쓰지 않습니다.

## 5. 백업·복원

| 단계 | 명령(예) | 검증 |
|---|---|---|
| 백업 | `pg_dump -Fc --no-owner --no-privileges -d <db> -f <file>` | 파일 sha256 기록, `pg_restore --list` 목차 확인 |
| 보관 | 접근 권한 700/600, 원본 서버 밖 사본 1개 이상 | sha256 재확인 |
| 격리 복원 훈련 | 새 일회용 DB에 `pg_restore --exit-on-error` | 표별 행 수·내용 md5·제약/인덱스 수 비교, 앱 `/health/db` |
| 자동 훈련 스크립트 | `database/tests/t90_backup_restore_drill.py` (loopback·`t90_*` DB만 허용) | 결과 JSON |
| 역할·권한 | 덤프에 포함하지 않음 → 권한 스크립트 별도 적용 | 앱 최소 권한 역할로 연결 확인 |

**훈련 기록**: 2026-11-11 로컬 PostgreSQL 18.6 격리 훈련 PASS ([매트릭스](RELEASE_TEST_MATRIX.md)). **Staging 실제 백업으로의 훈련은 미실시**입니다.

## 6. 장애 대응 순서

1. `hold.json`·배포 로그로 실패 단계를 확인합니다(게시·승인·digest·Health).
2. 서비스 영향이 있으면 §3-B(승인)를 검토하고, 없으면 §3-A로 진행합니다.
3. DB 문제는 쓰기를 중단하고 §5 격리 복원으로 판단합니다.
4. 개인정보 영향(유출·삭제 실패)은 PM·보안 담당에게 즉시 알립니다. 감사 기록·요청 ID로 범위를 확인합니다(T84 감사 API).

## 7. 인수인계 체크리스트

| 항목 | 상태 |
|---|---|
| 배포 추적 체인 (SHA → 이미지 digest → Staging 버전) | 문서화, Staging 버전 일치 확인 |
| CD 승인자·운영자 연락 체계 | PM 확인 필요 |
| Staging 호스트 접근 권한·백업 저장 위치 | 운영자 보유 (이 문서에 기록하지 않음) |
| 미해결 P0 | [Gate §4·§5](FINAL_RELEASE_GATE.md) |
| 미해결 Finding | F-1 접근 로그(T86), F87-1 감사 기록(T87), F-2·F-3 Low |
| 미병합 검증 PR | T87 #189, T88 #190, T89 #191 |
| Mock 기능 (운영 미활성) | T82 검수 UI, T85 감사·비용 UI, 분석 Mock provider |
