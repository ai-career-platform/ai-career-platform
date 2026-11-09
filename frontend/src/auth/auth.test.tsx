import { act, fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router';
import type { RouteObject } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { AccountPage } from '../pages/AccountPage';
import { LoginPage } from '../pages/LoginPage';
import { routes } from '../routes';
import { AuthProvider } from './AuthContext';
import { RequireAuth } from './RequireAuth';

// 이 파일의 모든 API 호출은 Mock 으로 처리한다 (T15 인증 API 구현 전).
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

// 역할 가드 검증용: 실제 routes 와 같은 구조에 /admin 만 추가한 트리.
const guardedRoutes: RouteObject[] = [
  {
    element: (
      <AuthProvider>
        <Outlet />
      </AuthProvider>
    ),
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/account', element: <AccountPage /> },
      {
        element: <RequireAuth roles={['admin']} />,
        children: [{ path: '/admin', element: <h1>관리자 화면</h1> }],
      },
    ],
  },
];

const setup = (path: string, tree: RouteObject[] = routes) => {
  const router = createMemoryRouter(tree, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
};

async function signIn(email: string, password = MOCK_PASSWORD) {
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: password } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

afterEach(() => vi.unstubAllGlobals());

describe('login flow', () => {
  it('logs in, lands on the account page, then logs out', async () => {
    setup('/login');
    await signIn('user@example.com');

    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    expect(screen.getByText(/user@example.com/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '로그아웃' }));
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
  });

  it('shows an error for wrong credentials (401)', async () => {
    setup('/login');
    await signIn('user@example.com', 'wrong-password');
    expect(await screen.findByRole('alert')).toHaveTextContent('이메일 또는 비밀번호가 올바르지 않습니다');
  });

  it('shows a retry message when rate limited (429)', async () => {
    setup('/login');
    await signIn('locked@example.com');
    expect(await screen.findByRole('alert')).toHaveTextContent('시도 횟수가 많습니다');
  });

  it('redirects anonymous users to login and back after signing in', async () => {
    setup('/account');
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();

    await signIn('admin@example.com');
    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    expect(screen.getByText(/job_seeker, admin/)).toBeInTheDocument();
  });
});

describe('role guard', () => {
  it('shows the 403 page when the user lacks the admin role', async () => {
    const router = setup('/login', guardedRoutes);
    await signIn('user@example.com');
    await screen.findByRole('heading', { name: '내 계정' });

    await act(() => router.navigate('/admin'));
    expect(await screen.findByRole('heading', { name: '접근 권한이 없습니다' })).toBeInTheDocument();
  });

  it('lets an admin through', async () => {
    const router = setup('/login', guardedRoutes);
    await signIn('admin@example.com');
    await screen.findByRole('heading', { name: '내 계정' });

    await act(() => router.navigate('/admin'));
    expect(await screen.findByRole('heading', { name: '관리자 화면' })).toBeInTheDocument();
  });
});
