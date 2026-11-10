import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../../mocks/handlers';
import { buildRoutes } from '../../routes';

// 기존 화면 테스트와 같이 Mock HTTP(handlers.ts)로 로그인합니다. 검수 기능 플래그는 buildRoutes 인자로 켜고 끕니다.
vi.mock('../../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false } }));

function open(path: string, adminModerationUi: boolean) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi }), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

async function login(email: string) {
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

describe('admin moderation routes', () => {
  it('flag off (default): no menu for an admin and the URL is not found', async () => {
    const router = open('/login', false);
    await login('admin@example.com');
    await screen.findByRole('link', { name: '운영 관리자' });   // logged in as the synthetic admin
    await router.navigate('/admin/moderation');
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: '주 메뉴' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '콘텐츠 검수 (Mock)' })).not.toBeInTheDocument();
  });

  it('the default exported routes keep the feature off', async () => {
    const { routes } = await import('../../routes');
    const paths = JSON.stringify(routes, (key, value) => (key === 'element' ? undefined : value));
    expect(paths).not.toContain('admin/moderation');
  });

  it('flag on: an anonymous direct URL goes to login', async () => {
    open('/admin/moderation/mc-00001', true);
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
  });

  it('flag on: a job seeker gets the 403 page and no menu', async () => {
    open('/admin/moderation', true);
    await login('user@example.com');
    expect(await screen.findByRole('heading', { name: '접근 권한이 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '콘텐츠 검수 (Mock)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: '검수 건 목록' })).not.toBeInTheDocument();
  });

  it('flag on: an admin sees the menu, the queue and a case (mock adapter)', async () => {
    open('/admin/moderation', true);
    await login('admin@example.com');
    expect(await screen.findByRole('heading', { name: '콘텐츠 검수' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '콘텐츠 검수 (Mock)' })).toHaveAttribute('href', '/admin/moderation');
    fireEvent.click(await screen.findByRole('link', { name: /mc-00003/ }, { timeout: 3000 }));
    expect(await screen.findByRole('heading', { name: '검수 건 mc-00003' }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '승인' })).toBeEnabled();
  });
});
