// Staging serves the app under /career/ on a shared origin where Redmine owns /. With the router basename
// every in-app link (logo, login, signup, guards, 404) must stay under /career/ and never point at /.
import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { routerBasename } from '../config/basePath';
import { routes } from '../routes';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/career/api', mockEnabled: true } }));

const BASENAME = routerBasename('/career/');

function open(path: string) {
  const router = createMemoryRouter(routes, { basename: BASENAME, initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}
// React Router renders the basename root as '/career'; the shared nginx redirects /career → /career/.
const CAREER_ROOT = /^\/career\/?$/;
const h1 = (name: string | RegExp) => screen.findByRole('heading', { level: 1, name });

describe('AI Career under /career (Redmine keeps /)', () => {
  it('/career/ opens the platform home, not the 404 page', async () => {
    open('/career/');
    expect(await screen.findByRole('heading', { level: 1 })).not.toHaveTextContent('페이지를 찾을 수 없습니다');
  });

  it('the logo links to /career/, never to the Redmine root', async () => {
    const router = open('/career/login');
    const logo = await screen.findByRole('link', { name: 'AI Career 홈' });
    expect(logo.getAttribute('href')).toMatch(CAREER_ROOT);
    fireEvent.click(logo);
    expect(router.state.location.pathname).toMatch(CAREER_ROOT);
    expect(await screen.findByRole('heading', { level: 1 })).not.toHaveTextContent('페이지를 찾을 수 없습니다');
  });

  it('/career/login and /career/signup open their screens, and the links between them stay under /career/', async () => {
    open('/career/login');
    expect(await h1('로그인')).toBeInTheDocument();
    const signup = screen.getByRole('link', { name: '회원가입' });
    expect(signup).toHaveAttribute('href', '/career/signup');
    fireEvent.click(signup);
    expect(await h1('회원가입')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '로그인' })).toHaveAttribute('href', '/career/login');
  });

  it('an anonymous visit to /career/account is sent to /career/login', async () => {
    const router = open('/career/account');
    expect(await h1('로그인')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/career/login');
  });

  it('a direct deep link (reload) to /career/signup routes correctly', async () => {
    const router = open('/career/signup');
    expect(await h1('회원가입')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/career/signup');
  });

  it('an unknown app path shows the platform 404 inside /career/', async () => {
    open('/career/does-not-exist');
    expect(await h1('페이지를 찾을 수 없습니다')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '홈으로 이동' }).getAttribute('href')).toMatch(CAREER_ROOT);
  });

  it('every in-app link on the home screen stays under /career/ (in-page #anchors aside)', async () => {
    open('/career/');
    await screen.findByRole('navigation', { name: '주 메뉴' });
    const hrefs = [...document.querySelectorAll('a')].map((a) => a.getAttribute('href') ?? '')
      .filter((href) => href.startsWith('/'));
    expect(hrefs.length).toBeGreaterThan(0);
    for (const href of hrefs) expect(href).toMatch(/^\/career(\/|$)/);
  });
});
