import type { RouteObject } from 'react-router';
import { AuthProvider } from './auth/AuthContext';
import { RequireAuth } from './auth/RequireAuth';
import { RecommendationFeedbackActions } from './components/RecommendationFeedbackActions';
import { AppLayout } from './layouts/AppLayout';
import { AccountPage } from './pages/AccountPage';
import { HomePage } from './pages/HomePage';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RecommendationsPage } from './pages/RecommendationsPage';
import { UiPreviewPage } from './pages/UiPreviewPage';

/**
 * 화면 라우트 목록. 새 화면은 pages/ 에 컴포넌트를 만들고 여기에 children 으로 추가합니다.
 * 화면 ID·경로는 docs/FULL_SCOPE_TRACEABILITY.md 기준으로 맞춥니다.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: (
      <AuthProvider>
        <AppLayout />
      </AuthProvider>
    ),
    children: [
      { index: true, element: <LandingPage /> },
      { path: 'system-status', element: <HomePage /> },
      { path: 'ui-preview', element: <UiPreviewPage /> },
      { path: 'login', element: <LoginPage /> },
      {
        element: <RequireAuth />,
        children: [
          { path: 'account', element: <AccountPage /> },
          // UI-017 맞춤 추천 (F-017). 카드의 공고 상세 링크 /job-postings/:id 화면은 T24 범위입니다.
          // 카드별 추천 설명 대화상자·피드백 버튼(F-018)은 T48 RecommendationFeedbackActions 로 연결합니다.
          {
            path: 'recommendations',
            element: (
              <RecommendationsPage
                renderItemActions={(item, run, onRunChange) => (
                  <RecommendationFeedbackActions item={item} run={run} onRunChange={onRunChange} />
                )}
              />
            ),
          },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];