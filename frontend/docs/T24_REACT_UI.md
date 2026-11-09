# T24 — 기업·채용공고 탐색 React UI (합성 데이터 시안)

상태: **T24_STATUS=PARTIAL / Draft review**. Redmine #1519. T24 기존 독립 HTML 초안 PR #31은 팀 관리자가 2026-11-09에 닫았다. 이전 PR은 재개하지 않고 최신 공용 main에 병합된 T20 공통 UI를 기반으로 별도 React 화면을 구현했다.

## 구현

- 경로: `/job-postings` (T23 직무 탐색 `/job-roles`와 별개).
- T20 `AppLayout`, `TextField`, `FilterChips`, `Button`, `StatePanel` 재사용. 화이트/인디고 테마 및 모바일 대응.
- 합성 기업 카드 4개, 합성 공고 8건(모집 6/마감 2) 노출. 별도 draft 데이터 1건은 항상 숨김.
- 채용공고/기업/기술 검색, 기업/직무 필터, 모집 중/마감/전체 상태 필터, 최신순/마감 임박순 정렬, 4건 단위 페이지 이동.
- 필터 및 페이지 조건을 브라우저 쿼리 파라미터에 반영. 검색 조건 변경 시 오래된 상세 정보 제거.
- 공고 상세: 기업·직무·지역·고용형태·게시일·마감일·가상 요구 기술·출처 코드.
- 로딩·빈 결과·Mock 실패·재시도·초기화 및 키보드 포커스.
- 기준일 `2026-11-09` 고정. 만료일은 합성 화면에서만 날짜까지 유효한 것으로 취급하고 실제 서버/시간대 정책과 동일하다고 주장하지 않는다.
- 원본 지원/기업 사이트 링크는 **검증 가능한 실 URL이 없으므로 제공하지 않음**. 실제 출처 권리·링크 유효성과 T18 데이터 계약 확인 후 연동.

## 주요 파일

| 파일 | 역할 |
|---|---|
| `frontend/src/pages/JobPostingsPage.tsx` | 화면, 필터/URL/상세/상태 관리 |
| `frontend/src/pages/JobPostingsPage.css` | 모바일 대응 전용 스타일 |
| `frontend/src/pages/jobPostingData.ts` | 합성 데이터 및 순수 검색/정렬/마감/페이지 로직 |
| `frontend/src/pages/JobPostingsPage.test.tsx` | Mock 테스트 |
| `frontend/src/routes.tsx` | `/job-postings` 라우트 1개 추가 |
| `frontend/src/layouts/AppLayout.tsx` | T20 사이드바에 진입 링크 추가 |
| `.github/workflows/t24-frontend.yml` | Frontend lint/typecheck/test/build 검사 |

## 검증 방법

Windows PowerShell에서 프로젝트 루트가 `C:\dev\team-project`라면:

```powershell
cd C:\dev\team-project\frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
npm run dev:mock
```

브라우저: `http://127.0.0.1:5173/job-postings`. 코드는 GitHub에서 작성했으므로 사용자의 실제 Windows PC에서 직접 실행하거나 시각/키보드 수동 검증했다고 주장하지 않는다. 실제 CI 결과는 PR 최신 SHA에 연결된 Actions 로그로 별도 확인한다.

## 선행조건 / 미결

- **T18 #128 Draft**: 정식 목록/상세, 커서 페이지네이션, 기업 ID·직무 ID, `published_at`/`expires_at`의 타임존/마감 정책과 `source_url` 사용권이 합의된 다음 `src/api/`에 클라이언트 어댑터를 추가한다. Mock의 페이지 번호는 정식 API 커서와 다르다.
- 실제 공고 출처, 면책 문구, 외부 리다이렉트/허용 도메인·링크 안전 검증은 미구현. 확인 안 된 URL을 만들지 않는다.
- 실제 API 연동, 인증/즐겨찾기, 팀 디자인 및 접근성 수동 QA, 공유 Staging 검증, PM/Redmine 최종 승인 전에는 완료 처리하지 않는다.
- T23 #130 역시 Draft이며 이 PR과 `frontend/src/routes.tsx` 및 `frontend/src/layouts/AppLayout.tsx`를 각각 수정하므로 병합 순서에 따라 두 경로가 함께 남는지 충돌 해결/재검증이 필요하다.

운영 API/DB/실제 개인정보/Staging/배포 및 공용 main 직접 변경: **없음**.
