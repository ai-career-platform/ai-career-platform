# T23 직무·기술 탐색 UI — React Mock

상태: **T23_STATUS=PARTIAL / review requested**. Redmine #1496. 과거 독립 HTML 시안은 팀에서 닫은 PR #30에 보존한다. 이번 구현은 T20 병합 후 최신 main을 기준으로 만든 별도 React 화면이다.

- 사용자 화면 경로: /job-roles
- 재사용: T20 AppLayout, Button, FilterChips, TextField, StatePanel 및 기본 디자인 토큰
- 기능: 직무/기술 검색, 분야 필터, 이름·분야 정렬, 페이지 이동, 직무 상세, 합성 요구 기술·수준 표시
- 상태: 기본/로딩/빈 결과/오류/재시도 및 검색 초기화
- 모바일에서는 목록과 상세를 세로로 배치한다.
- 직무 8개 및 요구 수준은 고정된 합성 데이터이다. T17 API 연결과 개인 보유 기술·Skill Gap 분석 결과는 구현하지 않았다.

## 구조

- src/pages/JobExplorerPage.tsx: React 상태 관리/공통 UI
- src/pages/JobExplorerPage.css: 모바일 대응 화면 스타일
- src/pages/jobExplorerData.ts: 합성 데이터 및 순수 검색/정렬/페이지 함수
- src/pages/JobExplorerPage.test.tsx: 사용자 상호작용·오류/재시도·페이지 단위 테스트
- src/routes.tsx: /job-roles 라우트 추가
- src/layouts/AppLayout.tsx: 사이드 메뉴의 직무·기술 탐색 링크 추가

## 실행 / 확인 (frontend 디렉터리)

    npm ci
    npm run lint
    npm run typecheck
    npm test
    npm run build
    npm run dev:mock

브라우저에서 http://127.0.0.1:5173/job-roles 로 확인한다. 팀 자동 CI는 .github/workflows/t23-frontend.yml 이다. 이 작업은 GitHub 기반으로 진행했으므로 실제 Windows 로컬 실행을 확인했다고 주장하지 않는다.

## 남은 사항

T17 PR #117은 Draft/HOLD 상태이므로 T17의 최종 목록·상세·검색 DTO 및 cursor 페이지네이션이 승인된 다음 API client를 src/api에 작성해야 한다. T33/T34 보유 기술 비교, T26 Skill Gap 분석, 실제 인증/권한, 실 DB, Staging/배포와 시각·접근성 수동 QA는 별도 선행·승인 후 작업한다. Mock 테스트 PASS는 서비스 완료가 아니다.

운영 API, 팀 공용 DB, 인증, Staging, 공용 main 직접 수정 없음.
