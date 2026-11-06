# T20 공통 컴포넌트 분리 검증

- 날짜: 2026-11-06
- 범위: 로컬 공통 컴포넌트 분리 및 랜딩 화면 회귀 검증
- 디자인: 검토 전 초안

## 구현
Header, Footer, Button, SectionHeading, FilterChips, JobCard, CompanyCard를 별도 파일로 분리했다.
각 컴포넌트는 자체 스타일을 import한다. 페이지 전용 배너와 검색 상태는 LandingPage에 유지한다.
기존 StatePanel, TextField, DataTable은 유지하고 미리보기 전용 FormPreview를 pages로 이동했다.
/ui-preview에 버튼, 필터, 공고 카드, 기업 카드 사용 예시를 추가했다.

## 자동 검사
- npm run lint: PASS
- npm run typecheck: PASS
- npm test: 4 files / 16 tests PASS
- npm run build: PASS
- git diff --check: PASS

검증 명령 실행 위치: frontend/
App.test.tsx의 헬스 API 테스트 경로는 /system-status로 수정했다.
LandingPage.test.tsx는 홈/내비게이션, 필터+검색, 빈 결과와 초기화, AI 안내, 버튼 비활성 및 기본 폼 제출 방지를 검증한다.
커밋 전 작업 트리 기준 결과이며 CI 및 커밋 SHA는 PR 제출 시 별도로 기록한다.

## 브라우저 수동 확인
- /: 랜딩 Header·배너·공고·기업 카드 렌더링 확인
- 개발 필터 선택: 4개에서 1개 공고로 변경
- 일치하지 않는 검색어 입력: 0개 및 빈 결과 안내
- 검색 조건 초기화: 4개 공고로 복귀
- 폭 390px: 반응형 배치 확인, documentElement.scrollWidth 375 <= innerWidth 390
- /ui-preview: 별도 페이지에서도 공통 카드 스타일 표시
- 공통 버튼 클릭 후 Enter 실행: 횟수 0 → 2

## 제한
가상 공고/기업 데이터이며 실제 API·인증·AI 기능 검증은 포함하지 않는다.
수동 확인은 위 항목 범위이며 전체 접근성 적합성 검증은 아니다.
최종 디자인 승인과 PR 리뷰·CI 결과는 별도 확인한다.