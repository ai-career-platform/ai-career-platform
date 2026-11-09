import type { RouteObject } from 'react-router';
import { AppLayout } from './layouts/AppLayout';
import { HomePage } from './pages/HomePage';
import { LandingPage } from './pages/LandingPage';
import { JobExplorerPage } from './pages/JobExplorerPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { UiPreviewPage } from './pages/UiPreviewPage';

/**
 * 화면 라우트 목록. 새 화면은 pages/ 에 컴포넌트를 만들고 여기에 children 으로 추가합니다.
 * 화면 ID·경로는 docs/FULL_SCOPE_TRACEABILITY.md 기준으로 맞춥니다.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <LandingPage /> },
      { path: 'system-status', element: <HomePage /> },
      { path: 'ui-preview', element: <UiPreviewPage /> },
      { path: 'job-roles', element: <JobExplorerPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];