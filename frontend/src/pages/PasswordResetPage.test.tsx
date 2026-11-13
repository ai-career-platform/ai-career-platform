/**
 * T94 계정 복구 화면 — Mock Adapter(합성 계정), 실제 메일·API 없음. 화면이 네트워크 요청을 보내면 실패합니다.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createHttpAccountRecoveryService, recoveryErrorView, REQUEST_PATH, RESET_PATH, type AccountRecoveryService,
} from '../api/accountRecovery';
import { ApiError } from '../api/errors';
import { createHttpClient } from '../api/http';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import { createMockAccountRecoveryService, type MockAccountRecoveryService } from '../mocks/accountRecovery';
import { PasswordResetPage } from './PasswordResetPage';

const NEW = 'new-correct-horse-94';
let fetchSpy: ReturnType<typeof vi.fn<typeof fetch>>;
let consoleSpies: Array<{ mock: { calls: unknown[][] } }>;
beforeEach(() => {
  fetchSpy = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetchSpy);
  consoleSpies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m));
});
afterEach(() => {
  const calls = fetchSpy.mock.calls.length;
  const logged = consoleSpies.flatMap((spy) => spy.mock.calls.map((args: unknown[]) => args.map(String).join(' ')));
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (calls) throw new Error(`the recovery UI sent ${calls} network request(s); only the mock adapter may be used`);
  if (logged.some((line) => /token|reset-token|new-correct-horse/i.test(line))) throw new Error('token or password reached the console');
});

const anonymous: AuthContextValue = { state: { status: 'anonymous' },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(), googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>() };
const signedIn: AuthContextValue = { state: { status: 'authenticated', token: 'synthetic', user: { email: 'user@example.com',
  displayName: '일반 사용자', roles: ['job_seeker'], userId: 'synthetic-user' } }, login: vi.fn<AuthContextValue['login']>(),
  logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(), googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>() };

function open(path: string, service: AccountRecoveryService | null, auth: AuthContextValue = anonymous) {
  const router = createMemoryRouter([
    { path: '/password-reset', element: <PasswordResetPage service={service} /> },
    { path: '/login', element: <h1>로그인</h1> },
    { path: '/account', element: <h1>내 계정</h1> },
  ], { initialEntries: [path] });
  render(<AuthContext.Provider value={auth}><RouterProvider router={router} /></AuthContext.Provider>);
  return router;
}
const type = (label: RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

async function requestFor(service: MockAccountRecoveryService, email: string) {
  open('/password-reset', service);
  type(/^이메일/, email);
  click('재설정 링크 받기');
  await screen.findByRole('heading', { name: '메일을 확인해 주세요' });
  return document.querySelector('[role=status]')!.textContent;
}

describe('request', () => {
  it('shows the same confirmation for an existing and an unknown account (no enumeration)', async () => {
    const service = createMockAccountRecoveryService();
    const known = await requestFor(service, 'user@example.com');
    document.body.innerHTML = '';
    const unknown = await requestFor(service, 'nobody@example.com');
    expect(known?.replace('재설정 링크 열기', '')).toContain('가입된 계정이 있으면');
    expect(unknown).toContain('가입된 계정이 있으면');
    expect(known?.split('가상 메일함')[0]).toBe(unknown?.split('가상 메일함')[0]);
  });

  it('rejects an invalid email before calling the service', () => {
    const service = createMockAccountRecoveryService();
    open('/password-reset', service);
    type(/^이메일/, 'not-an-email');
    click('재설정 링크 받기');
    expect(screen.getByRole('alert')).toHaveTextContent('이메일 주소 형식');
    expect(service.calls).toEqual([]);
  });

  it('503 (no mail provider) and 429 show fixed messages', async () => {
    open('/password-reset', createMockAccountRecoveryService({ unavailable: true }));
    type(/^이메일/, 'user@example.com');
    click('재설정 링크 받기');
    expect(await screen.findByRole('alert')).toHaveTextContent('메일을 보낼 수 없습니다');
    document.body.innerHTML = '';
    const limited = createMockAccountRecoveryService({ limitPerEmail: 0 });
    open('/password-reset', limited);
    type(/^이메일/, 'user@example.com');
    click('재설정 링크 받기');
    expect(await screen.findByRole('alert')).toHaveTextContent('요청이 너무 많습니다');
  });
});

describe('reset link', () => {
  it('removes the token from the URL immediately and keeps it out of the page', async () => {
    const service = createMockAccountRecoveryService();
    await service.requestReset({ email: 'user@example.com' });
    const token = service.lastIssuedToken()!;
    const router = open(`/password-reset?token=${token}`, service);
    await screen.findByRole('heading', { name: '새 비밀번호 설정' });
    await waitFor(() => expect(router.state.location.search).toBe(''));
    expect(document.body.innerHTML).not.toContain(token);
    expect(document.title).not.toContain(token);
  });

  it('validates the new password locally, then succeeds and points to login', async () => {
    const service = createMockAccountRecoveryService();
    await service.requestReset({ email: 'user@example.com' });
    open(`/password-reset?token=${service.lastIssuedToken()}`, service);
    await screen.findByRole('heading', { name: '새 비밀번호 설정' });
    type(/^새 비밀번호 \(필수\)/, 'short');
    type(/^새 비밀번호 확인/, 'short');
    click('비밀번호 바꾸기');
    expect(screen.getByRole('alert')).toHaveTextContent('10자 이상');
    type(/^새 비밀번호 \(필수\)/, NEW);
    type(/^새 비밀번호 확인/, NEW + 'x');
    click('비밀번호 바꾸기');
    expect(screen.getByRole('alert')).toHaveTextContent('같지 않습니다');
    expect(service.calls.filter((c) => c.path === RESET_PATH)).toEqual([]);
    type(/^새 비밀번호 확인/, NEW);
    click('비밀번호 바꾸기');
    expect(await screen.findByRole('heading', { name: '비밀번호를 바꿨습니다' })).toHaveFocus();
    expect(screen.getByText(/모든 기기에서 로그아웃/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '로그인하기' })).toHaveAttribute('href', '/login');
  });

  it.each(['expired', 'reused', 'forged'])('%s link shows the invalid screen with a way to request again', async (kind) => {
    const service = createMockAccountRecoveryService();
    await service.requestReset({ email: 'user@example.com' });
    let token = service.lastIssuedToken()!;
    if (kind === 'expired') service.expire(token);
    if (kind === 'reused') await service.resetPassword({ token, new_password: NEW });
    if (kind === 'forged') token = 'forged-token-0123456789-abcdef';
    open(`/password-reset?token=${token}`, service);
    await screen.findByRole('heading', { name: '새 비밀번호 설정' });
    type(/^새 비밀번호 \(필수\)/, NEW);
    type(/^새 비밀번호 확인/, NEW);
    click('비밀번호 바꾸기');
    expect(await screen.findByRole('heading', { name: '링크를 사용할 수 없습니다' })).toBeInTheDocument();
    click('새 링크 요청');
    expect(await screen.findByRole('heading', { name: '비밀번호 재설정' })).toBeInTheDocument();
  });
});

describe('other states', () => {
  it('a signed-in user gets a notice instead of the forms', async () => {
    open('/password-reset?token=anything-0123456789', createMockAccountRecoveryService(), signedIn);
    expect(await screen.findByRole('heading', { name: '이미 로그인되어 있습니다' })).toBeInTheDocument();
    expect(screen.queryByLabelText(/^이메일/)).toBeNull();
    expect(screen.getByRole('link', { name: '내 계정으로 이동' })).toBeInTheDocument();
  });

  it('without a service (non-mock build, T93 not merged) the page says it is not available yet', async () => {
    open('/password-reset', null);
    expect(await screen.findByRole('heading', { name: '비밀번호 재설정 준비 중' })).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('every input is labelled and errors are announced', async () => {
    open('/password-reset?token=x'.repeat(1), createMockAccountRecoveryService());
    await screen.findByRole('heading', { name: '새 비밀번호 설정' });
    for (const input of document.querySelectorAll('input')) expect((input as HTMLInputElement).labels?.length).toBeGreaterThan(0);
    click('비밀번호 바꾸기');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await act(async () => undefined);
  });
});

// ---------------------------------------------------------------- HTTP adapter ↔ confirmed contract (fake fetch)
describe('HTTP adapter (prepared, not selected)', () => {
  const SPEC = readFileSync(resolve(cwd(), '../docs/api/openapi.yaml'), 'utf8').replace(/\r\n/g, '\n');

  it('paths and bodies follow requestPasswordReset / resetPassword without an Authorization header', async () => {
    expect(SPEC).toContain('  /auth/password-reset-requests:');
    expect(SPEC).toContain('  /auth/password-resets:');
    const local = vi.fn<typeof fetch>(async () => new Response(null, { status: 202 }));
    const service = createHttpAccountRecoveryService(createHttpClient({ baseUrl: '/api', fetch: local, getToken: () => 'should-not-be-sent' }));
    await service.requestReset({ email: 'user@example.com' });
    local.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await service.resetPassword({ token: 't'.repeat(43), new_password: NEW });
    const [first, second] = local.mock.calls;
    expect(String(first![0])).toBe('/api' + REQUEST_PATH);
    expect(String(second![0])).toBe('/api' + RESET_PATH);
    expect(JSON.parse(String(first![1]!.body))).toEqual({ email: 'user@example.com' });
    expect(Object.keys(JSON.parse(String(second![1]!.body))).sort()).toEqual(['new_password', 'token']);
    for (const call of local.mock.calls) expect((call[1]!.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('server errors map to fixed messages that never reveal whether an account exists', () => {
    for (const [status, code] of [[400, 'INVALID_RESET_TOKEN'], [429, 'RATE_LIMITED'], [503, 'DEPENDENCY_UNAVAILABLE'], [422, 'VALIDATION_FAILED']] as const) {
      const view = recoveryErrorView(new ApiError(status, RESET_PATH, undefined, code, 'raw server text'));
      expect(view.message).not.toContain('raw server text');
      expect(view.message).not.toMatch(/존재하지 않|등록되지 않|가입되지 않/);
    }
  });
});
