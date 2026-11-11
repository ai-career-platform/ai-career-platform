import type { RouteObject } from 'react-router';
import { AuthProvider } from './auth/AuthContext';
import { RequireAuth } from './auth/RequireAuth';
import { ModerationServiceProvider } from './admin/ModerationServiceProvider';
import { env } from './config/env';
import { AppLayout } from './layouts/AppLayout';
import { AccountPage } from './pages/AccountPage';
import { PrivacySettingsPage } from './pages/PrivacySettingsPage';
import { HomePage } from './pages/HomePage';
import { LandingPage } from './pages/LandingPage';
import { JobExplorerPage } from './pages/JobExplorerPage';
import { LoginPage } from './pages/LoginPage';
import { PasswordResetPage } from './pages/PasswordResetPage';
import { MySkillsPage } from './pages/MySkillsPage';
import { MyDocumentsPage } from './pages/MyDocumentsPage';
import { MarketTrendsPage } from './pages/MarketTrendsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RecommendationsPage } from './pages/RecommendationsPage';
import { UiPreviewPage } from './pages/UiPreviewPage';
import { JobPostingsPage } from './pages/JobPostingsPage';
import { BookmarksPage, CareerHistoryPage, TargetRolesPage } from './pages/MyCareerWorkspace';
import { ModerationCasePage } from './pages/admin/ModerationCasePage';
import { ModerationQueuePage } from './pages/admin/ModerationQueuePage';
import { AdminAuditServiceProvider } from './admin/AdminAuditServiceProvider';
import { AiUsagePage } from './pages/admin/AiUsagePage';
import { AuditEventsPage } from './pages/admin/AuditEventsPage';
import { NotificationServiceProvider } from './notifications/NotificationServiceProvider';
import { NotificationsPage } from './pages/NotificationsPage';
import { NotificationSettingsPage } from './pages/NotificationSettingsPage';
import { ApplicationServiceProvider } from './applications/ApplicationServiceProvider';
import { ApplicationsBoardPage } from './pages/ApplicationsBoardPage';
import { PortfolioServiceProvider } from './portfolio/PortfolioServiceProvider';
import { PublicProfileSettingsPage } from './pages/PublicProfileSettingsPage';
import { PublicPortfolioViewPage } from './pages/PublicPortfolioViewPage';

/**
 * 화면 라우트 목록. 새 화면은 pages/ 에 컴포넌트를 만들고 여기에 children 으로 추가합니다.
 * 화면 ID·경로는 docs/FULL_SCOPE_TRACEABILITY.md 기준으로 맞춥니다.
 */
export type Features = { adminModerationUi: boolean; adminAuditUi?: boolean; notificationsUi?: boolean; jobSearchAdvancedUi?: boolean; applicationsUi?: boolean; publicPortfolioUi?: boolean };

/**
 * UI-028 운영 감사·AI 사용량(T85)도 같은 방식: 기능 플래그(Mock 모드 전용, env.ts)가 켜졌을 때만 경로·메뉴가 생기고,
 * 켜져 있어도 admin 역할만 들어갑니다. 권한(admin.audit.read) 회수는 서버 403 으로 화면에 표시합니다.
 */
const adminAuditRoutes = (features: Features): RouteObject[] => (features.adminAuditUi ? [
  { element: <RequireAuth roles={['admin']} />, children: [
    { element: <AdminAuditServiceProvider />, children: [
      { path: 'admin/audit-events', element: <AuditEventsPage /> },
      { path: 'admin/ai-usage', element: <AiUsagePage /> },
    ] },
  ] },
] : []);

/**
 * UI-N04 알림함·UI-005 알림 수신 설정(T97)도 같은 방식: 기능 플래그(Mock 모드 전용)가 켜졌을 때만 경로·메뉴가 생기고,
 * 로그인 사용자만 들어갑니다. 알림·설정은 로그인 사용자 ID 별로 분리됩니다(NotificationServiceProvider).
 */
const notificationRoutes = (features: Features): RouteObject[] => (features.notificationsUi ? [
  { element: <RequireAuth />, children: [
    { element: <NotificationServiceProvider />, children: [
      { path: 'me/notifications', element: <NotificationsPage /> },
      { path: 'me/notification-settings', element: <NotificationSettingsPage /> },
    ] },
  ] },
] : []);

/** T130 공개 포트폴리오: Mock 전용. 설정은 로그인 필요, 공개 화면(/p/:token)은 로그인 없이(같은 Provider = 같은 Mock 저장소) */
const portfolioRoutes = (features: Features): RouteObject[] => (features.publicPortfolioUi ? [
  { element: <PortfolioServiceProvider />, children: [
    { path: 'p/:token', element: <PublicPortfolioViewPage /> },
    { element: <RequireAuth />, children: [
      { path: 'me/public-profile', element: <PublicProfileSettingsPage /> },
    ] },
  ] },
] : []);

/** T103 개인 지원 현황 보드: Mock 전용, 사용자별 격리 */
const applicationRoutes = (features: Features): RouteObject[] => (features.applicationsUi ? [
  { element: <RequireAuth />, children: [
    { element: <ApplicationServiceProvider />, children: [
      { path: 'me/applications', element: <ApplicationsBoardPage /> },
    ] },
  ] },
] : []);

/**
 * UI-027 관리자 검수(T82)는 기능 플래그가 켜졌을 때만 경로·메뉴가 생깁니다(기본 꺼짐, Mock 모드 전용 — env.ts).
 * 꺼져 있으면 /admin/moderation 은 404 화면입니다. 켜져 있어도 admin 역할만 들어갑니다(RequireAuth).
 */
const adminRoutes = (features: Features): RouteObject[] => (features.adminModerationUi ? [
  { element: <RequireAuth roles={['admin']} />, children: [
    { element: <ModerationServiceProvider />, children: [
      { path: 'admin/moderation', element: <ModerationQueuePage /> },
      { path: 'admin/moderation/:caseId', element: <ModerationCasePage /> },
    ] },
  ] },
] : []);

export const buildRoutes = (
  features: Features = {
    adminModerationUi: env.adminModerationUi, adminAuditUi: env.adminAuditUi, notificationsUi: env.notificationsUi, jobSearchAdvancedUi: env.jobSearchAdvancedUi, applicationsUi: env.applicationsUi, publicPortfolioUi: env.publicPortfolioUi,
  },
): RouteObject[] => [
  {
    path: '/',
    element: (
      <AuthProvider>
        <AppLayout adminModerationUi={features.adminModerationUi} adminAuditUi={features.adminAuditUi ?? false}
          notificationsUi={features.notificationsUi ?? false} applicationsUi={features.applicationsUi ?? false}
          publicPortfolioUi={features.publicPortfolioUi ?? false} />
      </AuthProvider>
    ),
    children: [
      { index: true, element: <LandingPage /> },
      { path: 'system-status', element: <HomePage /> },
      { path: 'job-roles', element: <JobExplorerPage /> },
      { path: 'ui-preview', element: <UiPreviewPage /> },
      { path: 'job-postings', element: <JobPostingsPage advanced={features.jobSearchAdvancedUi ?? false} /> },
      { path: 'login', element: <LoginPage /> },
      // UI-N03 계정 복구 (T94). Mock 모드에서만 동작. 실제 API(T93 PR 195)는 미병합이라 일반 빌드는 '준비 중' 안내
      { path: 'password-reset', element: <PasswordResetPage /> },
      { element: <RequireAuth />, children: [
        { path: 'account', element: <AccountPage /> },
        { path: 'account/privacy', element: <PrivacySettingsPage /> },
        { path: 'me/target-roles', element: <TargetRolesPage /> },
        { path: 'me/career-history', element: <CareerHistoryPage /> },
        { path: 'me/bookmarks', element: <BookmarksPage /> },
        { path: 'me/skills', element: <MySkillsPage /> },
        { path: 'me/documents', element: <MyDocumentsPage /> },
        // UI-017 맞춤 추천 (F-017). 카드의 공고 상세 링크 /job-postings/:id 화면은 T24 범위입니다.
        { path: 'recommendations', element: <RecommendationsPage /> },
        // UI-024 채용시장 추세 (F-024). T67 GET /api/v1/market-trends 는 로그인 사용자만 조회합니다.
        { path: 'market-trends', element: <MarketTrendsPage /> },
      ] },
      ...notificationRoutes(features),
      ...applicationRoutes(features),
      ...portfolioRoutes(features),
      ...adminRoutes(features),
      ...adminAuditRoutes(features),
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

export const routes: RouteObject[] = buildRoutes();
