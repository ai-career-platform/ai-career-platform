# Ubuntu Staging 운영 Runbook

> 2026-11-05 수동 PoC 검증 기록 기반. 변경 전 현재 상태를 재점검하세요.

## 환경
- SSH: `kant@10.2.10.104` (사설 IP, 외부 Actions Runner가 직접 접근할 수 없음)
- OS: Ubuntu 26.04.1 LTS
- 배포 경로: `/home/kant/ai-career-staging-poc`
- Compose 프로젝트: `ai-career-staging-poc`
- Frontend 호스트 바인딩(목표 설정): `127.0.0.1:18080:80` **유지** + `10.2.10.104:18080:80` **추가**. 실제 서버 적용/네트워크 ACL은 별도 검증 필요.
- Backend: Docker 내부 `8000/tcp`; DB: 내부 `5432/tcp`.
- PoC는 `frontend`, `backend`, `db`로 구성; DB Named Volume `ai-career-staging-poc_postgres_data`.

## 2026-11-05 ~ 2026-11-06 검증 증빙
- `docker compose config --quiet` → PASS.
- Backend/Frontend 이미지 빌드 PASS.
- `docker compose ps db` → healthy.
- `docker compose ps backend` → healthy.
- Backend `/health/db` → HTTP 200; Nginx `/api/health/db` → HTTP 200.
- Frontend `http://127.0.0.1:18080/` → HTTP 200, text/html.
- 브라우저 렌더링 및 ngrok 외부 HTTPS는 아직 검증되지 않았음.
- 당시 다른 운영 컨테이너 18개가 존재했으며 현재 수량은 변할 수 있습니다. 프로젝트 외 리소스 보호가 우선입니다.
- 2026-11-06 PR #4 자동 배포 후 Frontend/Backend/DB Healthy, `/api/version` = `b1ce5e671bac271bc16a0692ab70d88a754c939c`. DB Container ID와 Named Volume 보존 확인.
- 2026-11-06 DB 초기화 전 백업 아카이브 검증 및 일회용 PostgreSQL 독립 복원 PASS. 사용자 정의 테이블 0개 확인; 실제 DB DDL/Seed 미적용.

## 읽기 전용 확인 명령
```bash
cd /home/kant/ai-career-staging-poc
docker compose ps
docker compose config --quiet
curl -fsS --max-time 10 http://127.0.0.1:18080/api/health
curl -fsS --max-time 10 http://127.0.0.1:18080/api/version
curl -fsS --max-time 10 http://127.0.0.1:18080/api/health/db
df -h /
free -h
```

## 운영 보호 조건
- 현재 호스트에는 **다른 운영 컨테이너 18개**가 있어 프로젝트명·네트워크·볼륨·포트를 반드시 구분.
- `.env`는 Git 미추적, 소유자 권한 600 유지. 공개 채팅/로그로 비밀번호 출력 금지.
- `docker compose down -v`, 전역 `docker system prune`, DB 볼륨 삭제, 기존 ngrok 변경 금지.
- CPU/메모리/디스크를 배포 전후 점검하고 컨테이너 재시작 급증 시 배포 중단.
- Staging DB는 초기화하지 않고 공통 Seed/샘플 데이터 보존.
- 문제 발생 시 변경한 **PoC 서비스만** 범위를 특정하여 조치하고 운영 서비스는 변경하지 않음.

## 수동 배포와 복구
- 수동 배포와 자동 배포 E2E 검증 완료(2026-11-06). 현재 배포 SHA는 `/api/version`, systemd journal 및 GitHub Actions에서 다시 확인.
- 자동 배포 기준은 CI 성공·이미지 Digest·허용 승인자·헬스체크. DB Migration은 별도 승인 절차로 실행.
- 장애 시 먼저 `docker compose ps`, 로그에서 비밀정보 배제한 상태로 확인. 승인 없는 광범위 정리/다운 금지.
- ngrok 외부 공개는 별도 검토; Pull형 CD에는 ngrok 불필요.


## LAN 바인딩 변경 절차 (서버 미적용 / 운영자 실행 필요)

> 변경된 소스 설정은 `poc/staging/compose.yaml`입니다. 실제 서버 파일은 자동으로 바뀌지 않을 수 있습니다. **Ubuntu 호스트에서 설정을 대조하고 운영자가 검증/적용해야 합니다.**

1. `ip -4 addr show`로 서버에 `10.2.10.104`가 실제 할당되어 있는지 확인합니다. 사설망/VPN 접근 사용자·방화벽 접근 정책을 검토합니다.
2. 기존 Ubuntu 배포 디렉터리 `/home/kant/ai-career-staging-poc/compose.yaml`을 백업하고 `frontend.ports`에 다음 **두 줄을 모두** 적용합니다.

   ```yaml
   ports:
     - "127.0.0.1:18080:80"
     - "10.2.10.104:18080:80"
   ```

3. 자동 배포 Overlay 사용 여부를 확인합니다. 해당 폴더에서 `docker compose --env-file .env config --quiet`를 검증합니다. 기존 포트 점유 상태 확인: `ss -ltn '( sport = :18080 )'`. IP/포트 충돌 및 사설망 접근제어 정책 미확정이면 HOLD.
4. 운영자가 Compose 변경을 확인한 후 **Frontend 서비스만** 재생성합니다. 데이터베이스·Backend 및 타 프로젝트는 건드리지 않습니다.

   ```bash
   cd /home/kant/ai-career-staging-poc
   docker compose --env-file .env up -d --no-deps --no-build frontend
   ```

   **주의:** 해당 Frontend가 GHCR Digest 기반으로 구동 중이라면 위 단순 명령이 기존 이미지를 변경할 위험이 있습니다. 그 경우 적용은 **기존 운영 Compose Overlay 및 검증된 FRONTEND_IMAGE/DEPLOY_SHA를 유지한 동일 Compose 인수**로 실행해야 합니다. 어떤 Compose 명령이 실제 구동에 사용되었는지 확인하지 못했다면 실행하지 말고 운영자에게 확인합니다.

5. 서버 내부에서 기존 `curl -fsS http://127.0.0.1:18080/api/health` 와 신규 `curl -fsS http://10.2.10.104:18080/api/health` 모두 확인한 뒤, 허가된 Windows/VPN 클라이언트에서 `http://10.2.10.104:18080/` 접속을 검증합니다.
6. `docker compose ps`, DB 컨테이너 ID/Named Volume 유지, 타 컨테이너 영향 없음, 기존 Pull형 배포 Health Check 통과 여부를 확인합니다.

**보안 경계:** 서버 IP는 사설 주소이나 같은 네트워크 전체에서 서비스가 열릴 수 있습니다. 방화벽/ACL을 허용된 개발자 네트워크로 제한하고, 개인 데이터 및 인증/인가가 완성되지 않은 서비스는 외부로 개방하지 않습니다. **0.0.0.0 포트 공개 금지.**

**롤백:** Frontend 두 번째 포트 바인딩만 제거하고, 실행에 사용 중인 원본 이미지·Overlay를 유지한 동일 방식으로 Frontend만 재생성. `docker compose down`, `down -v`, 전체 `prune` 금지.
