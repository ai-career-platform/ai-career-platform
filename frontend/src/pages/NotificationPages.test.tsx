/**
 * T97 알림함·수신 설정 — 실제 라우터(buildRoutes) + Mock HTTP 로그인 + 알림 Mock Adapter.
 * 실제 알림 API·메일 발송은 없습니다(Mock PASS 이며 실제 API PASS 가 아님).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { MOCK_PASSWORD } from '../mocks/handlers';
import type { MockNotificationBackend, MockNotificationOptions } from '../mocks/notifications';
import { buildRoutes } from '../routes';

const holder = vi.hoisted(() => ({
  backend: null as MockNotificationBackend | null,
  seed: undefined as MockNotificationOptions['seed'],
}));

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false, notificationsUi: false } }));
// 화면이 만드는 Mock backend 를 시험이 붙잡아 실패 주입·사용자 간 공유에 씀(지연 0)
vi.mock('../mocks/notifications', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/notifications')>();
  return {
    ...original,
    createMockNotificationBackend: (options: MockNotificationOptions = {}) => {
      holder.backend ??= original.createMockNotificationBackend({ ...options, latencyMs: 0, seed: holder.seed });
      return holder.backend;
    },
  };
});

const USER = 'user@example.com';
const ADMIN = 'admin@example.com';

beforeEach(() => { holder.backend = null; holder.seed = undefined; });

async function open(path: string, as?: string, notificationsUi = true) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: false, notificationsUi }),
    { initialEntries: [as ? '/login' : path] });
  render(<RouterProvider router={router} />);
  if (as) {
    fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: as } });
    fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await screen.findByRole('link', { name: as === ADMIN ? '운영 관리자' : '일반 사용자' });
    // 로그인 후 /account 이동이 끝난 다음 딥링크로 이동한다. CI의 비동기 경합 방지.
    await screen.findByRole('heading', { name: '내 계정' });
    await act(() => router.navigate(path));
  }
  return router;
}

const unreadBadges = () => screen.queryAllByText('안 읽음', { selector: '.notify-unread' });

describe('feature flag and access', () => {
  it('flag off: no menu and both URLs are not found, even when logged in', async () => {
    await open('/me/notifications', USER, false);
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '알림함 (Mock)' })).not.toBeInTheDocument();
  });

  it('the default routes keep the feature off and the flag needs mock mode', async () => {
    const { routes } = await import('../routes');
    const paths = JSON.stringify(routes, (key, value) => (key === 'element' ? undefined : value));
    expect(paths).not.toContain('me/notifications');
    const env = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    expect(env).toContain("notificationsUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_NOTIFICATIONS_UI === 'true'");
    const provider = readFileSync(resolve(cwd(), 'src/notifications/NotificationServiceProvider.tsx'), 'utf8');
    expect(provider).not.toMatch(/fetch\(|HttpClient|useApi/);
  });

  it.each(['/me/notifications', '/me/notification-settings'])('anonymous %s goes to login', async (path) => {
    await open(path);
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
  });
});

describe('inbox', () => {
  it('shows read and unread items with a text label, and marks one then all as read', async () => {
    await open('/me/notifications', USER);
    expect(await screen.findByText('안 읽은 알림 2건')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '알림함 (Mock)' })).toBeInTheDocument();
    expect(screen.getByText(/가상 데이터\(Mock\)/)).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
    expect(unreadBadges()).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: '새 기기 로그인 읽음으로 표시' }));
    expect(await screen.findByText('안 읽은 알림 1건')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('‘새 기기 로그인’을 읽음으로 표시했습니다.');
    expect(unreadBadges()).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: '모두 읽음으로 표시' }));
    expect(await screen.findByText('안 읽은 알림 0건')).toBeInTheDocument();
    expect(unreadBadges()).toHaveLength(0);
    expect(screen.getByRole('button', { name: '모두 읽음으로 표시' })).toBeDisabled();
    expect(holder.backend!.snapshot(USER).inbox.every((x) => x.read_at)).toBe(true);
  });

  it('keeps users apart: one user reading everything does not touch another user', async () => {
    await open('/me/notifications', USER);
    fireEvent.click(await screen.findByRole('button', { name: '모두 읽음으로 표시' }));
    await screen.findByText('안 읽은 알림 0건');
    cleanup();

    await open('/me/notifications', ADMIN);                 // 같은 Mock backend, 다른 사용자
    expect(await screen.findByText('안 읽은 알림 2건')).toBeInTheDocument();
    const adminService = holder.backend!.serviceFor(ADMIN);
    const userItemId = holder.backend!.snapshot(USER).inbox[0]!.notification_id;
    await expect(adminService.markRead(userItemId)).rejects.toMatchObject({ status: 404 });
    const userIds = new Set(holder.backend!.snapshot(USER).inbox.map((x) => x.notification_id));
    expect(holder.backend!.snapshot(ADMIN).inbox.some((x) => userIds.has(x.notification_id))).toBe(false);
    expect([...userIds].join()).not.toContain('@');
  });

  it('shows the empty state', async () => {
    holder.seed = () => [];
    await open('/me/notifications', USER);
    expect(await screen.findByText('받은 알림이 없습니다')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '모두 읽음으로 표시' })).not.toBeInTheDocument();
  });

  it('shows a load error with retry, and a failed mark-read keeps the item unread', async () => {
    const router = await open('/account', USER);
    await act(() => router.navigate('/me/notifications'));
    // 첫 진입 전에 backend 가 만들어지므로 다음 조회를 실패시키고 다시 들어감
    await screen.findByText('안 읽은 알림 2건');
    holder.backend!.failNext('inbox');
    await act(() => router.navigate('/me/notification-settings'));
    await act(() => router.navigate('/me/notifications'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('알림을 불러오지 못했습니다');
    expect(alert).toHaveTextContent('서버에 연결하지 못했습니다');
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('안 읽은 알림 2건')).toBeInTheDocument();

    holder.backend!.failNext('read');
    fireEvent.click(screen.getByRole('button', { name: '새 맞춤 추천 3건 읽음으로 표시' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 연결하지 못했습니다');
    expect(screen.getByText('안 읽은 알림 2건')).toBeInTheDocument();
    expect(unreadBadges()).toHaveLength(2);
  });
});

describe('preferences', () => {
  it('required types are on and locked; marketing and recommendations are off until the user opts in', async () => {
    await open('/me/notification-settings', USER);
    const password = await screen.findByRole('checkbox', { name: '비밀번호 변경' });
    expect(password).toBeChecked();
    expect(password).toBeDisabled();
    expect(password).toHaveAccessibleDescription(/필수 알림 — 끌 수 없음/);
    for (const name of ['새 로그인', '약관·정책 변경', '탈퇴 처리 안내']) {
      expect(screen.getByRole('checkbox', { name })).toBeDisabled();
    }
    expect(screen.getByRole('checkbox', { name: '소식·혜택(광고)' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: '새 맞춤 추천' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: '서비스 점검' })).toBeChecked();
    expect(screen.getAllByRole('group').map((g) => g.querySelector('legend')?.textContent)).toEqual(
      ['계정 보안', '계정', '서비스 안내', '추천', '마케팅']);
  });

  it('opting in saves and is reflected in the stored preferences', async () => {
    await open('/me/notification-settings', USER);
    const marketing = await screen.findByRole('checkbox', { name: '소식·혜택(광고)' });
    fireEvent.click(marketing);
    expect(await screen.findByRole('status')).toHaveTextContent('소식·혜택(광고) 알림을 받습니다. 동의 이력에 기록됩니다.');
    expect(marketing).toBeChecked();
    expect(holder.backend!.snapshot(USER).preferences.find((p) => p.type === 'marketing.newsletter')!.enabled).toBe(true);
    expect(holder.backend!.snapshot(ADMIN).preferences.find((p) => p.type === 'marketing.newsletter')!.enabled).toBe(false);

    fireEvent.click(marketing);
    expect(await screen.findByRole('status')).toHaveTextContent('받지 않습니다');
    expect(marketing).not.toBeChecked();
  });

  it('a failed save rolls back to the previous value and announces it', async () => {
    await open('/me/notification-settings', USER);
    const recommendation = await screen.findByRole('checkbox', { name: '새 맞춤 추천' });
    holder.backend!.failNext('update');
    fireEvent.click(recommendation);
    expect(await screen.findByRole('alert')).toHaveTextContent('새 맞춤 추천: 서버에 연결하지 못했습니다');
    await waitFor(() => expect(recommendation).not.toBeChecked());
    expect(recommendation).toBeEnabled();
    expect(holder.backend!.snapshot(USER).preferences.find((p) => p.type === 'recommendation.new_results')!.enabled).toBe(false);
  });

  it('shows a load error with retry', async () => {
    const router = await open('/account', USER);
    await act(() => router.navigate('/me/notifications'));
    await screen.findByText('안 읽은 알림 2건');
    holder.backend!.failNext('preferences');
    await act(() => router.navigate('/me/notification-settings'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('설정을 불러오지 못했습니다');
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('checkbox', { name: '비밀번호 변경' })).toBeInTheDocument();
  });
});

describe('mock adapter contract (T95 proposal rules)', () => {
  it('rejects turning off a required type with 422 and leaves everything unchanged', async () => {
    const { createMockNotificationBackend } = await vi.importActual<typeof import('../mocks/notifications')>('../mocks/notifications');
    const backend = createMockNotificationBackend();
    const service = backend.serviceFor('u1');
    const error = await service.updatePreferences({ items: [
      { type: 'marketing.newsletter', enabled: true }, { type: 'security.new_login', enabled: false }] }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect(backend.snapshot('u1').preferences.find((p) => p.type === 'marketing.newsletter')!.enabled).toBe(false);
    await expect(service.updatePreferences({ items: [] })).rejects.toMatchObject({ status: 422 });
  });

  it('the inbox summary carries no links, tokens or e-mail addresses', async () => {
    const { createMockNotificationBackend } = await vi.importActual<typeof import('../mocks/notifications')>('../mocks/notifications');
    const page = await createMockNotificationBackend().serviceFor('u1').listInbox();
    const text = JSON.stringify(page.items.map(({ title, summary }) => ({ title, summary })));
    expect(text).not.toMatch(/https?:|token|@/i);
  });
});
