# GitHub Actions + Ubuntu Pull형 Staging CD 설계

## 목표
PM/JM이 PR을 `main`에 Squash Merge → Actions CI 통과 → 검증된 불변 배포 아티팩트 게시 → Ubuntu `systemd timer`가 1분 주기로 확인 → 변경 시에만 Compose 배포.

## 구현 상태 (2026-11-06, PR #4 자동 배포 E2E 기준)
- PR #1 초기 Smoke CI와 PR #3 Auto-CD 코드 Merge 완료. PR #4 검증 Merge SHA `b1ce5e671bac271bc16a0692ab70d88a754c939c` 자동 배포 PASS (당시 기준 SHA).
- 기존 CI는 README 파일 존재 여부 등 **Smoke 테스트만** 수행. 전체 품질/보안/배포 게이트가 아님.
- GHCR 게시 및 Ubuntu Pull 자동 배포 코드는 PR #3으로 Merge 완료; systemd 배포 service/timer 설치·활성화, 중복 SHA 방지와 실제 배포를 검증했습니다.
- GitHub main CI·GHCR 게시, 이미지 Digest 고정, 승인자 매핑, PR #4 Merge → Ubuntu 자동 배포 E2E PASS. 인증 토큰 만료·교체는 운영 관리 대상입니다.
- `ai-career-staging-deploy.timer` 설치·활성화, 1분 폴링과 동일 SHA 중복 배포 방지 확인. DB Migration은 자동 실행하지 않습니다.

## 신뢰할 수 있는 배포 버전
- Repo/Branch `ai-career-platform/ai-career-platform:main`, Commit SHA, CI 성공 여부를 연계하여 검증.
- `main` HEAD라는 이유만으로 배포 금지.
- 권장: CI 성공 시 SHA 기반 이미지와 Digest 고정 Manifest를 GHCR에 게시.
- 공개 패키지 또는 안전한 인증 토큰을 사용하여 Ubuntu에서 조회. 토큰을 코드/로그에 남기지 않음.
- 초기에는 DB Migration이 포함된 배포를 자동 승인하지 않음.

## Ubuntu Poll 방식
- Ubuntu에서만 GitHub/GHCR로 HTTPS Outbound 연결; GitHub Actions에 서버 사설 IP/SSH 키 등록 불필요.
- 1분마다 가벼운 배포 신호 확인. SHA가 동일하면 즉시 종료하며 Docker Pull/Build 생략.
- `flock` 잠금 및 중복 SHA 방지, 단일 Compose 프로젝트 범위 제한.
- 새 버전만 Frontend/Backend 교체. 기존 DB Named Volume 보존; DB DDL 변경 별도 승인.
- Health Check: `/`, `/api/health`, `/api/version`, `/api/health/db`, 기대 SHA/버전 검증.
- 성공 기록과 실패 기록 분리; 실패 시 성공 처리 금지. 자동 롤백은 사전 검증 전까지 비활성화.

## 1분 systemd 타이머
- 예정 유닛: `ai-career-staging-deploy.service`, `ai-career-staging-deploy.timer`.
- `Type=oneshot`; 실행 사용자 `kant`; 겹침 방지; 표준 출력 비밀정보 배제.
- `OnBootSec`/`OnUnitInactiveSec`는 직전 실행 완료 기준이므로 **정확한 매 분 정각 보장은 아님**. 요구하는 폴링 지연을 운영 테스트로 검증.
- 가벼운 HTTP 확인도 네트워크·CPU 부하는 0이 아님; 중요한 자원 부하는 이미지 Pull 및 배포 시 발생.

## 활성화 전 필수 게이트
1. 실제 CI 테스트 강화 및 `main` 성공 증빙.
2. GHCR Write/Read 및 Digest 고정 검증.
3. PM/JM 승인자 로그인 매핑.
4. 자동화 코드 PR 리뷰·Squash Merge.
5. Ubuntu Staging 비활성 설치 및 Dry Run.
6. 락·중복 방지·실패·Health Check 검증.
7. 보호된 환경에서 Timer 활성화, 기존 운영 컨테이너 영향 확인.

## 복구
- 마지막 Healthy 이미지 Digest를 기록하고, 복구는 검토된 절차로 수행.
- CI 실패/미확인, 잘못된 Repo/SHA, 인증 불명확, DB Migration 요청 시 배포 **HOLD**.
- 실패 시 `main`을 임의로 되돌리거나 호스트 Docker 리소스를 전역 정리하지 않음.
