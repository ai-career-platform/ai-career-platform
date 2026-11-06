import { NavLink } from 'react-router';
import './Header.css';

export type HeaderLink = { href: string; label: string };
type HeaderProps = {
  brand?: string;
  homeTo?: string;
  links?: readonly HeaderLink[];
  wide?: boolean;
};

export function Header({ brand = 'AI Career', homeTo = '/', links = [], wide = false }: HeaderProps) {
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
    </header>
  );
}
