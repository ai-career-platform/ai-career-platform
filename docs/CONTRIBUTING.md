# GitHub · Slack · 코드 리뷰 운영 규정

## 기본 흐름
1. 개발자는 Redmine Issue를 선택하고 개별 기능 브랜치를 만듭니다.
2. 코드·테스트·필요한 문서를 포함해 PR을 생성합니다.
3. CI 결과와 자체 검증을 확인하고 Slack `#ai-career-pr-review`에 Merge 검토를 요청합니다.
4. **PM/JM 중 먼저 확인한 사람**이 스레드에 '검토 시작'을 남겨 담당을 확정합니다.
5. 승인자는 GitHub의 파일 변경·코드·테스트·보안·DB 변경 여부를 검토합니다.
6. 모든 GitHub Ruleset 조건 충족 시 **Squash Merge**합니다.
7. Merge SHA, Staging 확인 결과를 Slack과 Redmine에 기록합니다.

## PR 템플릿
```text
[PR 리뷰 및 Merge 요청]
- 담당 개발자:
- Redmine Issue:
- PR URL:
- 구현/변경 내용:
- 영향 범위: Frontend / Backend / DB / AI-ML / 기타
- 테스트·Swagger·UI Preview 증빙:
- DB Schema 또는 Seed 변경: YES / NO
- 위험/복구/특이사항:
```

## 승인 원칙
- 원칙적으로 작성자 외 1명 이상이 리뷰합니다.
- GitHub에서 필수 승인 1건, 대화 해결, 허용된 Merge 방식 등 Ruleset을 따릅니다.
- PM/JM의 Bypass는 초기 기반 구성 등 제한적 예외로만 사용하며, 사용 사유를 PR에 기록합니다.
- Bypass 권한은 지속적 예외이므로 주기적으로 재검토합니다.
- CI가 실패하면 Merge하지 않습니다. 단, CI PASS가 전체 기능 품질을 증명하지는 않습니다.
- Design Review가 필요한 화면 변경은 MG 피드백을 반영합니다.
- DB 변경이 포함된 PR은 [DATABASE.md](DATABASE.md)의 별도 승인 절차를 따릅니다.

## 리뷰 중단 조건
- SECRET/개인정보 유출, 무단 DB Migration, 실패한 테스트, API 계약 불일치, 승인 없는 운영 설정 변경, 근거 없는 'PASS' 표기.

## 현재 CI에 관한 주의
`.github/workflows/ci.yml`은 T28에서 Smoke CI에 Backend/PoC pytest, Frontend lint·test·build(T19 `frontend/`), ruff(E9·F), Markdown 링크, Secret 패턴 검사를 추가한 경량 PR 게이트입니다(상세·로컬 실행: [QUALITY.md](QUALITY.md)). DB 변경은 별도 PostgreSQL 격리 검증 CI(`d1-postgres-sql-test.yml`)가 확인하며, PR #3/4의 GHCR→Ubuntu Auto-CD E2E도 검증되었습니다. 이 CI가 전체 서비스 품질·보안을 자동 보증하지는 않습니다.
