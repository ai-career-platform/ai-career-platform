# T30 — 1차 Staging PoC 릴리스 증빙 및 복구 확인

> 2026-11-09 PM 경량 범위 확정: **기존 정적 Frontend + FastAPI + PostgreSQL의 Staging CD/운영 PoC**만 T30의 완료 범위로 본다. T19 React 앱의 Staging 배포 및 T29 전체 화면/API E2E는 **별도 후속 일감**이다.
>
> 이 문서는 기존 검증 기록을 **재사용**하는 릴리스 증빙 인덱스다. 이 PR에서 Ubuntu/Staging 서버에 접속하거나 실배포·DB 변경·장애 주입·복원을 새로 실행하지 않았다. 과거 PASS 기록을 2026-11-09 현재 서버의 실시간 상태로 오인하지 않는다.

## 1. 확인된 코드·배포 범위

| 항목 | 저장소 증거 | 판단 |
| --- | --- | --- |
| main CI | [`ci.yml`](../../.github/workflows/ci.yml) | PR/push CI 구현 확인; 특정 배포 SHA의 CI 성공 여부는 해당 실행 기록 별도 확인 |
| GHCR 이미지 게시·Digest Manifest | [`staging-publish.yml`](../../.github/workflows/staging-publish.yml), [`publish.py`](../../poc/staging/automation/publish.py) | 이미지 SHA 태그·digest 고정 게시 로직 구현 확인 |
| Ubuntu Pull형 CD | [`deploy.py`](../../poc/staging/automation/deploy.py), [CI/CD Runbook](../CI_CD.md) | systemd 폴링·승인 확인·Digest 검증·동일 SHA 방지·Health Gate 구현 및 과거 E2E PASS 기록 |
| Staging Health | [Staging 운영 기록](../STAGING.md) | 2026-11-06 당시 `/`, `/api/health`, `/api/version`, `/api/health/db` PASS 기록 |
| DB 보존·복구 | [Staging 운영 기록](../STAGING.md), [배포 테스트](../../poc/staging/automation/tests/test_deploy.py) | DB 컨테이너/볼륨 보존 기록, 백업 아카이브 검증 및 **일회용 PostgreSQL 독립 복원** PASS 기록 |
| 실제 인증/프로필 DB 기능 | [T16 통합 경계](../../poc/staging/T16_INTEGRATION.md), [PR #126](https://github.com/ai-career-platform/ai-career-platform/pull/126) | 2026-11-09 담당자 보고: T15/T16 Staging PostgreSQL 연동 PASS, Backend 173 PASS; 별도 원본 Evidence는 이 PR에서 재검증하지 않음 |
| Frontend 이미지 | [게시 workflow](../../.github/workflows/staging-publish.yml), [PoC Dockerfile](../../poc/staging/frontend/Dockerfile) | 배포되는 것은 `poc/staging/frontend/index.html` **정적 Nginx PoC**; `frontend/` React 빌드가 아님 |

### 과거 확인된 배포 SHA / 실행 증빙

- **2026-11-06:** [Staging 운영 기록](../STAGING.md)에 PR #4 자동배포 후 `/api/version` = `b1ce5e671bac271bc16a0692ab70d88a754c939c`, Frontend/Backend/DB Healthy, DB Container ID·Named Volume 보존이 기록되어 있다.
- **2026-11-09 담당자 보고:** PR #126 병합 및 Staging SHA `dbaa4ed916200c8262acd5127757c5a197dbacfa`에서 T15/T16 실제 PostgreSQL 검증, Commit/Rollback, 격리 및 데이터 원상 복구가 PASS라고 보고되었다. 이는 **제출된 결과 보고**이며, 이 PR에서 동일 호스트에 재접속하거나 원본 로그의 해시를 대조한 것은 아니다.
- **현재 동작 SHA / 이미지 Digest / 배포 run URL:** `NOT_VERIFIED_IN_THIS_PR`. 실제 현재 호스트 상태는 서버의 `/api/version` 및 `.deploy-state/success.json`, GitHub 게시 run / manifest의 SHA·Digest를 비교해야 한다. 저장소 `main` HEAD와 배포 SHA가 반드시 같다고 가정하지 않는다.

## 2. 운영자가 추가 확인할 때의 읽기 전용 명령

서버 운영자가 필요할 때만 `docs/STAGING.md` 절차에 따라 실행한다. **이번 T30 문서 PR의 선행조건으로 재배포하지 않는다.**

```bash
cd /home/kant/ai-career-staging-poc
docker compose ps
docker compose config --quiet
curl -fsS --max-time 10 http://127.0.0.1:18080/
curl -fsS --max-time 10 http://127.0.0.1:18080/api/health
curl -fsS --max-time 10 http://127.0.0.1:18080/api/version
curl -fsS --max-time 10 http://127.0.0.1:18080/api/health/db
```

검증 기록에는 실행 시각, 배포 Manifest SHA/Backend·Frontend image Digest, `/api/version` 응답 SHA, 세 컨테이너 Health, DB 컨테이너·Volume 식별자 **변경 여부만** 적는다. 비밀번호·환경변수·전체 `docker inspect` 출력은 남기지 않는다.

## 3. 장애·복구 Runbook (기존 구현 재사용)

- 게시/승인/Checksum 실패 또는 미확인: **배포 HOLD**. 실패를 정상 배포로 표시하지 않는다.
- 배포 후 헬스 실패: [`deploy.py`](../../poc/staging/automation/deploy.py)의 실패/HOLD 기록을 확인하고, 변경된 **PoC 서비스**만 조사한다. 기존 `success.json`과 `previous.json` 상태를 운영자가 확인한다. **자동 롤백을 수행했다고 주장하지 않는다.**
- 이전에 검증된 이미지 Digest 및 DB 백업을 바탕으로 복구 계획을 검토한다. 실제 복구가 필요할 때는 [Staging Runbook](../STAGING.md) 절차에 따라 별도 수행한다.
- DB named volume 보존. `docker compose down -v`, 전역 `docker system prune`, DB 자동 초기화·Migration, 다른 Compose 프로젝트 리소스 변경 금지.
- 2026-11-06의 **일회용 DB 복원 PASS**는 기존 Staging DB를 실제로 복원한 기록과 다르다. 현재 장애 상황에 대한 운영 복구 완료 증빙으로 확대 해석하지 않는다.

## 4. T30 경량 DoD 및 후속 범위

| 완료 기준 | 상태 |
| --- | --- |
| CD 파이프라인 구축 및 1차 Ubuntu 자동배포 검증 | **PASS (기존 Runbook의 과거 검증 기록)** |
| 정적 Frontend / Backend / PostgreSQL PoC Healthy | **PASS (기존 과거 Staging 기록)** |
| 이미지 Digest 고정, DB 보존 및 복구 절차 | **PASS (구현·기존 검증 기록)** |
| 최신 GitHub PR의 문서 변경 및 CI | **본 PR의 체크 결과로 별도 판정** |
| React `frontend/`의 실제 Staging 배포 | **FOLLOW_UP (T19/T29 연계)** |
| 사용자 전체 화면/API E2E 및 HTTPS 브라우저 Refresh | **FOLLOW_UP** |
| 2026-11-09 현재 배포 SHA/Digest 및 실시간 호스트 상태 | **NOT_VERIFIED** |

**PM 범위 판정:** `T30_POC_SCOPE=PASS_BASED_ON_EXISTING_EVIDENCE`, `T30_REACT_FULL_INTEGRATION=FOLLOW_UP`, `T30_CURRENT_STAGING_STATE=NOT_VERIFIED_IN_THIS_PR`.

본 PR은 **문서 보완만** 수행하며 서비스/DB/Auto-CD를 변경하지 않는다. React 통합 배포의 완료를 주장하지 않는다.
