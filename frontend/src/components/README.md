# T20 공통 UI 컴포넌트

상태: 디자인 검토 전 초안

## 미리보기

frontend 폴더에서 실행:

    npm ci
    npm run dev:mock

접속: http://127.0.0.1:5173/ui-preview

미리보기는 가상 데이터와 상태를 사용한다.
폼 제출과 재시도 예시는 실제 API 호출이나 저장을 수행하지 않는다.

## 구성

| 항목 | 위치 | 역할 |
|---|---|---|
| AppLayout | ../layouts/AppLayout.tsx | Header, Sidebar, 본문, Footer |
| StatePanel | ./StatePanel.tsx | 로딩·빈 데이터·오류·권한 없음 |
| TextField | ./TextField.tsx | 라벨·필수 표시·도움말·오류가 연결된 입력란 |
| DataTable | ./DataTable.tsx | 공통 표 및 로딩·빈 데이터·오류 상태 |
| FormPreview | ../pages/FormPreview.tsx | 입력 검증 동작 예시. 제품 화면용 공통 폼은 아님 |

## 사용 규칙

### StatePanel

- variant: loading / empty / error / unauthorized
- title, description으로 화면에 맞는 문구 지정
- 동작 버튼이 필요하면 actionLabel과 onAction을 함께 전달
- 서버 내부 경로, 오류 스택, 민감정보를 문구에 표시하지 않음

### TextField

- label은 반드시 제공
- required로 필수 입력 표시
- hint는 입력 도움말, error는 검증 오류 문구
- 입력값과 검증 로직은 사용하는 화면에서 관리
- name, type, value, onChange 등 기본 input 속성 전달 가능
- 도움말·오류는 aria-describedby로 입력란과 연결

### DataTable

- caption: 표 제목
- columns: 열 key, header, render 정의
- rows: 표시할 데이터
- getRowKey: 각 행의 고유하고 안정적인 key 반환
- loading, error, 빈 rows에 따라 공통 상태 UI 표시
- onRetry로 재시도 동작 연결
- 오류 문구는 사용자에게 공개 가능한 안내문으로 전달
- 정렬·페이지네이션·행 선택은 현재 범위에 포함되지 않음

## 공통 스타일 규칙

- 색상은 src/styles/global.css의 기존 CSS 변수를 사용
- 현재 색상·디자인 토큰은 검토 전 초안
- 이 작업에서 주로 사용하는 간격: 8 / 12 / 16 / 24 / 32px
- 입력란과 버튼의 최소 높이: 44px
- 키보드 포커스는 눈에 보이는 outline으로 표시
- 오류는 색상과 설명 문구를 함께 제공

## 반응형·접근성

- 767px 이하에서 Sidebar를 본문 위로 배치
- 좁은 화면에서 표 영역 내부 가로 스크롤 제공
- 본문 바로가기 링크 제공
- 입력란 label 연결, 필수·오류 상태 제공
- 표 caption 및 열 제목 scope 제공
- 움직임 감소 설정에서는 로딩 회전 애니메이션 중지

## 자동 테스트

CommonUi.test.tsx에서 확인:
- 오류 상태 재시도 콜백
- 입력란 라벨·필수·도움말·오류 연결
- 빈 표 상태
- 빈 폼 제출 시 오류 및 첫 입력란 포커스
- 정상 입력 시 검증 통과 안내

## 미확정·후속 확인

- 최종 디자인 및 스타일 승인
- 역할별 메뉴와 실제 인증 상태 연결
- 로그인 필요·404·점검 중 등 추가 공통 상태 요구사항 검토
- 실제 Backend API 연동
- 모바일·키보드·접근성 수동 점검 결과 기록

자동 테스트 통과만으로 전체 접근성 또는 실제 API 연동 완료로 판단하지 않는다.

## 메인 페이지에서 분리한 공통 컴포넌트

| 컴포넌트 | props / 역할 |
|---|---|
| Header | brand, homeTo, links(href/label), wide. React Router 내부에서 사용 |
| Footer | children, wide. 하단 안내 영역 |
| Button | variant(primary/outline), disabled, onClick 및 기본 button 속성. 기본 type=button |
| SectionHeading | id, title, eyebrow, aside. 제목과 우측 부가 정보 |
| FilterChips | label, options(value/label), value, onChange. 선택 상태는 부모에서 관리 |
| JobCard | job: JobCardData, tagsLabel(기본 `관련 기술`). 공고의 제목·기업·태그 표시. tags가 비면 목록을 그리지 않음 |
| CompanyCard | company: CompanyCardData. 기업명·설명·톤 표시 |

각 컴포넌트는 자신의 CSS를 직접 import하며 LandingPage.css에 의존하지 않습니다.
CardTone.css는 공고·기업 카드의 공통 색상 변형을 제공합니다.
전체 앱의 기본 색상 변수는 src/styles/global.css에서 제공합니다.
메인 장식 배너와 검색·필터 상태는 LandingPage가 담당합니다.
카드는 현재 정보 표시 전용이며 상세 페이지 링크를 제공하지 않습니다.

사용 예:

```tsx
<Button variant="outline" onClick={reset}>초기화</Button>
<FilterChips label="직무 선택" options={options} value={category} onChange={setCategory} />
<JobCard job={job} />
<CompanyCard company={company} />
```

미리보기: /ui-preview에서 버튼·선택 필터·채용 카드·기업 카드를 확인합니다.
Header/Footer는 각 화면의 실제 레이아웃에서 확인합니다.
개발 상태 화면은 /system-status, 서비스 메인은 /입니다.
FormPreview, TablePreview, LandingComponentsPreview는 pages/의 미리보기 전용 예시입니다.

LandingPage.test.tsx는 홈 라우팅·필터/검색 조합·초기화·AI 안내·버튼 비활성 및 폼 제출 방지를 검증합니다.
App.test.tsx의 헬스 API 검증은 /system-status에서 유지합니다.
