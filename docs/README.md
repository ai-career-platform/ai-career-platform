# AI Career Platform — 협업 및 운영 가이드

> 문서 최초 작성: 2026-11-05 · 운영 상태 확인: 2026-11-06. 이 문서는 프로젝트 운영 기준 초안입니다. 기술 상태는 해당 시점의 증빙과 구분하며, 미구현 사항을 완료로 해석하지 않습니다.

## 빠른 시작
1. [신규 개발자 온보딩](ONBOARDING.md)
2. [협업 및 Git/PR 규정](CONTRIBUTING.md)
3. [Redmine 업무·진척률 관리](REDMINE.md)
4. [DB 접근·변경 및 Seed 정책](DATABASE.md)
5. [시스템 아키텍처 및 API 계약](ARCHITECTURE.md)
6. [Staging 운영 가이드](STAGING.md)
7. [CI/CD 자동 배포 설계](CI_CD.md)
8. [보안·시크릿·접근 권한](SECURITY.md)
9. [테스트 및 완료 증빙](QUALITY.md)
10. [AI/ML·LLM 통합 원칙](AI_FEATURES.md)

## 역할
- **개발자**: Redmine 세부일감 선택·개발·자체 테스트·PR 및 Slack 리뷰 요청.
- **JM(PL)**: 코드/아키텍처 리뷰, GitHub 승인·Merge, 승인된 DB 변경.
- **PM**: 범위·일정·운영 승인, 리뷰·Merge, DB 운영 책임.
- **MG(디자인 검토)**: Preview UI·화면 흐름 검토, 디자인 피드백.
- GitHub 권한과 담당자 계정 매핑은 실제 팀 등록 결과를 확인해야 합니다.

## 공통 원칙
- 모든 코드 변경은 개인 브랜치 → PR → CI → 승인·Merge를 원칙으로 합니다.
- Merge 승인은 GitHub에서, 요청/알림은 Slack에서 처리합니다.
- Redmine 진행률 0/10/90/100% 규정을 사용합니다.
- Staging DB는 공동 테스트 공간이며 공통 Seed 데이터를 보존합니다.
- DB Schema/Migration 변경은 PM/JM 승인 전에는 실행하지 않습니다.
- 운영 비밀정보, SSH 비밀번호, 실제 개인정보는 GitHub/Slack에 등록하지 않습니다.
- Staging 자동 배포(1분 타이머)는 2026-11-06 기준 실제 PR #4 E2E 검증을 완료했습니다. 일반 앱 배포와 DB Migration은 분리합니다.

## 현황 확인
GitHub PR, Actions, Redmine, Ubuntu의 실행 상태는 각각 별도로 확인합니다. 이 문서는 실시간 상태표가 아닙니다.

## 필수 일감 종료 게이트 (모든 T01~T150 및 신규 개발 일감)

**[Auto-CD → Staging QA → Redmine CLOSED 공통 규정](WORK_ITEM_CLOSURE_GATE.md)**을 개별 작업지시서의 DoD와 함께 반드시 적용합니다. `main` 병합 후 **기존 자동 배포가 실제 해당 기능을 포함했는지 → 게시/Ubuntu Pull 성공 → 실제 실행 SHA 및 Staging 기능 테스트 → Evidence → Redmine 100% CLOSED** 순서를 확인합니다. **MERGED, CI SUCCESS, PoC Health PASS만으로 CLOSED 금지**. 미대상 기능은 배포되었다고 가정하지 않으며 `DEPLOY_SCOPE_GAP/HOLD` 처리합니다. 문서 전용 작업은 PM/JM이 명시적으로 승인한 N/A 대체 검증을 따릅니다.
