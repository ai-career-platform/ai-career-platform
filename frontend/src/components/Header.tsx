import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import './Header.css';

export type HeaderLink = { href: string; label: string };
type HeaderProps = {
  brand?: string;
  homeTo?: string;
  links?: readonly HeaderLink[];
  wide?: boolean;
  /** 로그인 링크·사용자 이름처럼 헤더 오른쪽에 둘 요소 */
  actions?: ReactNode;
};

export function Header({ brand = 'AI Career', homeTo = '/', links = [], wide = false, actions }: HeaderProps) {
  return (
    <header className={`app-header${wide ? ' app-header--wide' : ''}`}>
      <NavLink to={homeTo} className="app-brand" aria-label={`${brand} 홈`}>
        {brand}<span className="brand-dot" aria-hidden="true">.</span>
      </NavLink>
      {links.length > 0 && (
        <nav aria-label="주 메뉴" className="landing-header-nav">
          {links.map((link) => <a key={link.href} href={link.href}>{link.label}</a>)}
        </nav>
      )}
      {actions && <div className="app-header-actions">{actions}</div>}
    </header>
  );
}
