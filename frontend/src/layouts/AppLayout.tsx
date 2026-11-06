import { NavLink, Outlet } from 'react-router';
import './AppLayout.css';

/**
 * 최소 골격 레이아웃 (T19).
 * 헤더·내비게이션·푸터의 실제 디자인과 공통 UI 컴포넌트는 T20에서 이 파일과 src/components/ 에 구현합니다.
 */
export function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink to="/" className="app-brand">
          AI Career Platform
        </NavLink>
        <nav aria-label="주 메뉴" className="app-nav">
          <NavLink to="/" end>
            홈
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
