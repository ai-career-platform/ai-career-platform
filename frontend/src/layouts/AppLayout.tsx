import { NavLink, Outlet, useLocation } from 'react-router';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import './AppLayout.css';

const homeLinks = [
  { href: '#positions', label: '채용 탐색' },
  { href: '#career', label: 'AI 커리어' },
  { href: '#companies', label: '기업 탐색' },
];

export function AppLayout() {
  const { pathname } = useLocation();
  const isHome = pathname === '/';

  return (
    <div className={`app-shell${isHome ? ' app-shell--landing' : ''}`}>
      <a href="#main-content" className="skip-link">
        본문으로 바로가기
      </a>

      <Header links={isHome ? homeLinks : undefined} wide={isHome} />

      <div className="app-body">
        {!isHome && (
          <aside className="app-sidebar">
            <nav aria-label="주 메뉴" className="app-nav">
              <NavLink to="/" end>
                홈
              </NavLink>
              <NavLink to="/ui-preview">
                공통 UI 미리보기
              </NavLink>
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