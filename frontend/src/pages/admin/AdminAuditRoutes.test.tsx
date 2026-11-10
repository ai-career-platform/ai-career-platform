/**
 * T85 경로·메뉴·관리자 권한 (기존 Mock HTTP 로그인 + 실제 RequireAuth). 기능 플래그는 buildRoutes 인자로 켜고 끕니다.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../../mocks/handlers';
import { buildRoutes } from '../../routes';

vi.mock('../../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false } }));

function open(path: string, adminAuditUi: boolean) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi }), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

async function login(email: string) {
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

describe('admin audit routes', () => {
  it('flag off (default): no menu for an admin and both URLs are not found', async () => {
    const router = open('/login', false);
    await login('admin@example.com');
    await screen.findByRole('link', { name: '운영 관리자' });
    for (const path of ['/admin/audit-events', '/admin/ai-usage']) {
      await router.navigate(path);
      expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    }
    expect(screen.queryByRole('link', { name: '운영 감사 (Mock)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'AI 사용량·비용 (Mock)' })).not.toBeInTheDocument();
  });

  it('the default exported routes keep the feature off', async () => {
    const { routes } = await import('../../routes');
    const paths = JSON.stringify(routes, (key, value) => (key === 'element' ? undefined : value));
    expect(paths).not.toContain('admin/audit-events');
    expect(paths).not.toContain('admin/ai-usage');
  });

  it('the feature flag requires mock mode (operating builds never enable it)', () => {
    const env = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    expect(env).toContain("adminAuditUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_ADMIN_AUDIT_UI === 'true'");
    const provider = readFileSync(resolve(cwd(), 'src/admin/AdminAuditServiceProvider.tsx'), 'utf8');
    expect(provider).not.toMatch(/import .*adminAuditHttp/);
  });

  it.each(['/admin/audit-events', '/admin/ai-usage'])('2. flag on: anonymous %s goes to login', async (path) => {
    open(path, true);
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
  });

  it.each(['/admin/audit-events', '/admin/ai-usage'])('3. flag on: a job seeker gets 403 at %s and no menu', async (path) => {
    open(path, true);
    await login('user@example.com');
    expect(await screen.findByRole('heading', { name: '접근 권한이 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '운영 감사 (Mock)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('1. flag on: an admin sees both menus and both screens with mock data', async () => {
    const router = open('/admin/audit-events', true);
    await login('admin@example.com');
    expect(await screen.findByRole('heading', { name: '운영 감사 기록' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '운영 감사 (Mock)' })).toHaveAttribute('href', '/admin/audit-events');
    expect(screen.getByRole('link', { name: 'AI 사용량·비용 (Mock)' })).toHaveAttribute('href', '/admin/ai-usage');
    expect(await screen.findByRole('table', { name: /감사 기록 목록/ }, { timeout: 3000 })).toBeInTheDocument();
    await router.navigate('/admin/ai-usage');
    expect(await screen.findByRole('heading', { name: 'AI 사용량·추정 비용' })).toBeInTheDocument();
    expect(await screen.findByText('표시 중: 가상 데이터(Mock)', undefined, { timeout: 3000 })).toBeInTheDocument();
  });
});
