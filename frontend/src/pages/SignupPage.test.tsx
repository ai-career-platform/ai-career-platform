import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { routes } from '../routes';

// 이 파일의 모든 API 호출은 Mock 으로 처리한다 (가짜 계정만 사용).
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

const setup = (path: string) => {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
};

async function fill(email: string, options: { password?: string; confirm?: string; agree?: boolean } = {}) {
  const password = options.password ?? 'synthetic-password-1';
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^이름/), { target: { value: '가짜 사용자' } });
  fireEvent.change(screen.getByLabelText(/^비밀번호 \(필수\)|^비밀번호$/), { target: { value: password } });
  fireEvent.change(screen.getByLabelText(/^비밀번호 확인/), { target: { value: options.confirm ?? password } });
  if (options.agree ?? true) {
    fireEvent.click(screen.getByLabelText(/이용약관 동의/));
    fireEvent.click(screen.getByLabelText(/개인정보 처리 동의/));
  }
  fireEvent.click(screen.getByRole('button', { name: '회원가입' }));
}

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe('signup page', () => {
  it('opens from the login page link instead of the not-found page', async () => {
    setup('/login');
    fireEvent.click(await screen.findByRole('link', { name: '회원가입' }));
    expect(await screen.findByRole('heading', { name: '회원가입' })).toBeInTheDocument();
    expect(screen.queryByText('페이지를 찾을 수 없습니다')).not.toBeInTheDocument();
  });

  it('lists required and optional policies from GET /consent-policies', async () => {
    setup('/signup');
    expect(await screen.findByLabelText(/이용약관 동의 \(필수\)/)).toBeRequired();
    expect(screen.getByLabelText(/개인정보 처리 동의 \(필수\)/)).toBeRequired();
    expect(screen.getByLabelText(/AI 처리 동의 \(선택\)/)).not.toBeRequired();
  });

  it('signs up, is logged in right away and lands on the account page', async () => {
    const router = setup('/signup');
    await fill('new-user@example.com');
    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/account');
  });

  it('shows a clear message for an email that is already registered (409)', async () => {
    setup('/signup');
    await fill('user@example.com');
    expect(await screen.findByRole('alert')).toHaveTextContent('이미 가입된 이메일입니다');
  });

  it('blocks a short password and a mismatched confirmation before calling the API', async () => {
    setup('/signup');
    await fill('short@example.com', { password: 'short' });
    expect(await screen.findByRole('alert')).toHaveTextContent('10자 이상');
    fireEvent.change(screen.getByLabelText(/^비밀번호 \(필수\)|^비밀번호$/), { target: { value: 'synthetic-password-1' } });
    fireEvent.change(screen.getByLabelText(/^비밀번호 확인/), { target: { value: 'synthetic-password-2' } });
    fireEvent.click(screen.getByRole('button', { name: '회원가입' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('비밀번호 확인이 일치하지 않습니다');
  });
});
