# 보안·권한·비밀정보 규정

## GitHub
- `main` 보호 Ruleset `protect-main`: PR 리뷰·승인(원칙 1명), CI, Squash Merge.
- 예외 Bypass는 PM 필요 시 PR에서만 제한적으로 사용; 사용 이력·이유 기록 및 정기 재검토.
- PM/JM 외 일반 개발자의 운영 배포·권한 변경 금지.
- GitHub App 설치는 Organization 저장소를 필요한 범위로만 허용.
- 민감정보/토큰/API Key/비밀번호를 코드·PR·Issues·Slack·Actions 로그에 게시하지 않음.

## Ubuntu/DB
- `.env`를 Git에 Commit하지 않으며 권한 600 유지.
- DB Backend 계정에는 SUPERUSER 금지, 필요한 CRUD만 부여.
- 개발자 reader 계정은 SELECT 중심, DDL/DML 불가. 공동 계정은 감사 추적 한계가 있어 개인 계정으로 전환 고려.
- DB 5432 외부 공개 금지; VPN 또는 SSH 터널 등 승인된 경로로만 접속.
- 기존 운영 호스트의 ngrok TCP 5432 터널은 별도 점검 필요; 새 PoC DB 노출과 혼동 금지.
- 테스트용 가상 데이터만 Staging에 사용하고 실사용자의 민감정보를 업로드하지 않음.

## AI/LLM
- 사용자 입력에 포함된 비밀·개인정보는 외부 LLM에 전송하기 전 최소화/마스킹.
- RAG 검색 결과를 신뢰된 시스템 지시로 취급하지 않고 Prompt Injection 방어.
- LLM 호출 예외/타임아웃 시 핵심 서비스 장애로 전파되지 않도록 격리.
- 요청 단위 토큰/비용 기록 시 원문 프롬프트·사용자 개인정보는 최소 수집.

## 권한 승인
- GitHub Actions, GHCR, Vault 등의 서비스 계정/토큰은 역할별 최소 권한.
- Secret 변경/권한 부여는 PM/JM 승인과 기록이 필요.
- 계정 탈퇴/역할 변경 시 권한 즉시 회수.
- 보안 사고 의심 시 관련 토큰 회전, 노출 범위 확인, 감사/복구 기록.
