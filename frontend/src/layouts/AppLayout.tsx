import { NavLink, Outlet, useLocation } from 'react-router';
import { useCrawlerNavigationEnabled } from '../admin/crawlerNavigation';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import './AppLayout.css';

const homeLinks = [
  { href: '#positions', label: '채용 탐색' },
  { href: '#career', label: 'AI 커리어' },
  { href: '#companies', label: '기업 탐색' },
];

export function AppLayout({ adminModerationUi = false, adminAuditUi = false, notificationsUi = false, applicationsUi = false, companyConsoleUi = false, publicPortfolioUi = false, personalDataUi = false }: {
  adminModerationUi?: boolean; adminAuditUi?: boolean; notificationsUi?: boolean; applicationsUi?: boolean; companyConsoleUi?: boolean; publicPortfolioUi?: boolean; personalDataUi?: boolean;
}) {
  const { pathname } = useLocation();
  const isHome = pathname === '/';
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.roles.includes('admin');
  // 관리자 메뉴: 기능 플래그(Mock 전용)가 켜져 있고 admin 역할일 때만. 경로 자체도 RequireAuth 로 막습니다.
  const showModeration = adminModerationUi && isAdmin;
  const showAudit = adminAuditUi && isAdmin;
  const showCrawler = useCrawlerNavigationEnabled() && isAdmin;
  // T97 알림함: 기능 플래그(Mock 전용)가 켜져 있고 로그인했을 때만
  const showNotifications = notificationsUi && state.status === 'authenticated';
  const showApplications = applicationsUi && state.status === 'authenticated';
  const showCompany = companyConsoleUi && state.status === 'authenticated';
  const showPortfolio = publicPortfolioUi && state.status === 'authenticated';
  const showPersonalData = personalDataUi && state.status === 'authenticated';
  const authLink =
    state.status === 'authenticated' ? (
      <NavLink to="/account">{state.user.displayName}</NavLink>
    ) : (
      state.status === 'anonymous' && <NavLink to="/login">로그인</NavLink>
    );

  return (
    <div className={`app-shell${isHome ? ' app-shell--landing' : ''}`}>
      <a href="#main-content" className="skip-link">
        본문으로 바로가기
      </a>

      <Header links={isHome ? homeLinks : undefined} wide={isHome} actions={authLink} />

      <div className="app-body">
        {!isHome && (
          <aside className="app-sidebar">
            <nav aria-label="주 메뉴" className="app-nav">
              <NavLink to="/" end>
                홈
              </NavLink>
              <NavLink to="/recommendations">
                맞춤 추천
              </NavLink>
              <NavLink to="/market-trends">
                채용시장 추세
              </NavLink>
              <NavLink to="/job-roles">
                직무·기술 탐색
              </NavLink>
              <NavLink to="/ui-preview">
                공통 UI 미리보기
              </NavLink>
              <NavLink to="/job-postings">
                기업·채용공고 탐색
              </NavLink>
              {showNotifications && <NavLink to="/me/notifications">{env.mockEnabled ? '알림함 (Mock)' : '알림함'}</NavLink>}
              {showApplications && <NavLink to="/me/applications">{env.mockEnabled ? '지원 현황 (Mock)' : '지원 현황'}</NavLink>}
              {showCompany && <NavLink to="/company">기업 콘솔 (Mock)</NavLink>}
              {showPortfolio && <NavLink to="/me/public-profile">{env.mockEnabled ? '공개 포트폴리오 (Mock)' : '공개 포트폴리오'}</NavLink>}
              {showPersonalData && <NavLink to="/me/data">{env.mockEnabled ? '내 데이터 내려받기 (Mock)' : '내 데이터 내려받기'}</NavLink>}
              {showModeration && <NavLink to="/admin/moderation">콘텐츠 검수 (Mock)</NavLink>}
              {showAudit && <NavLink to="/admin/audit-events">운영 감사 (Mock)</NavLink>}
              {showAudit && <NavLink to="/admin/ai-usage">AI 사용량·비용 (Mock)</NavLink>}
              {showCrawler && <NavLink to="/admin/crawler">크롤러 관리</NavLink>}
            </nav>
          </aside>
        )}

        <main id="main-content" className="app-main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>

      <Footer wide={isHome} />
    </div>
  );
}