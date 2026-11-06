import type { ReactNode } from 'react';
import './Footer.css';

export function Footer({ children = 'AI Career Platform · 디자인 검토 전 화면 초안', wide = false }: {
  children?: ReactNode;
  wide?: boolean;
}) {
  return <footer className={`app-footer${wide ? ' app-footer--wide' : ''}`}>{children}</footer>;
}
