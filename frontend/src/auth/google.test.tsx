/**
 * #328 STEP 03-b Google 로그인 화면 시험. 실제 Google·Backend 대신 가짜 fetch(아래 `backend`)로 Backend 계약
 * (docs/api/openapi.yaml: /auth/gate, /auth/google/pending|signup|signout, /auth/refresh)을 흉내 냅니다.
 * Mock 모드(VITE_API_MOCK)는 끈 상태로 실제 HTTP 클라이언트·라우터·AuthProvider 를 그대로 씁니다.
 */
import { act, cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { routes } from '../routes';
import {
  GOOGLE_LOGIN_ERRORS, googleLoginError, googleStartHref, isSafeAppPath, navigation, nextAppPath,
} from './google';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false } }));

// 전체 스위트 병렬 실행 중에는 여러 단계의 fetch 가 1초 기본 대기를 넘을 수 있어(1회 관찰) 이 파일만 5초로 둡니다.
configure({ asyncUtilTimeout: 5000 });

type Call = { method: string; path: string; body?: unknown; headers: Record<string, string> };

const POLICIES = [
  { policy_code: 'terms', version: '2026-11', is_required: true, content_url: 'https://docs.invalid/t', effective_at: '2026-11-06T00:00:00Z' },
  { policy_code: 'privacy', version: '2026-11', is_required: true, content_url: 'https://docs.invalid/p', effective_at: '2026-11-06T00:00:00Z' },
  { policy_code: 'llm_processing', version: '2026-11', is_required: false, content_url: 'https://docs.invalid/l', effective_at: '2026-11-06T00:00:00Z' },
];

/** 가짜 Backend. 기본은 Google 켜짐, refresh 쿠키 없음, pending 있음. */
function backend(options: {
  google?: 'off' | 'on'; refresh?: boolean; pending?: 'ok' | 'expired' | 'not_allowed';
  signup?: 'ok' | 'expired' | 'conflict' | 'not_allowed' | 'network' | 'validation';
} = {}) {
  const calls: Call[] = [];
  let refreshCookie = options.refresh ?? false;
  const json = (status: number, body?: unknown) =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status, headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    });
  const problem = (status: number, code: string) => json(status, { code, status, message: code });
  const token = { access_token: 'synthetic-access', token_type: 'Bearer', expires_in: 900 };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(String(input), 'https://app.invalid');
    const path = url.pathname.replace(/^\/api/, '');
    const method = init?.method ?? 'GET';
    const headers = Object.fromEntries(new Headers(init?.headers).entries());
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, headers });
    const google = options.google ?? 'on';
    if (path.startsWith('/v1/auth/google') || path === '/v1/auth/gate') {
      if (google === 'off') return problem(404, 'NOT_FOUND');
    }
    if (method === 'GET' && path === '/v1/auth/gate') return problem(401, 'EDGE_AUTH_REQUIRED');
    if (method === 'POST' && path === '/v1/auth/refresh') {
      return refreshCookie ? json(200, token) : problem(401, 'UNAUTHENTICATED');
    }
    if (method === 'POST' && path === '/v1/auth/logout') { refreshCookie = false; return json(204); }
    if (method === 'POST' && path === '/v1/auth/google/signout') { refreshCookie = false; return json(204); }
    if (method === 'GET' && path === '/v1/me') {
      return json(200, { user_id: 'u-1', email: 'google.user@example.com', display_name: '구글 사용자', status: 'active',
        profile: { headline: null, bio: null, location_text: null }, created_at: '2026-11-13T00:00:00Z' });
    }
    if (method === 'GET' && path === '/v1/me/permissions') return json(200, { roles: ['job_seeker'], permissions: [] });
    if (method === 'GET' && path === '/v1/consent-policies') return json(200, POLICIES);
    if (method === 'GET' && path === '/v1/auth/google/pending') {
      if (options.pending === 'expired') return problem(401, 'GOOGLE_SIGNUP_EXPIRED');
      if (options.pending === 'not_allowed') return problem(403, 'GOOGLE_NOT_ALLOWED');
      return json(200, { email: 'google.user@example.com', display_name: '구글 사용자', expires_at: '2026-11-13T01:00:00Z' });
    }
    if (method === 'POST' && path === '/v1/auth/google/signup') {
      switch (options.signup) {
        case 'expired': return problem(401, 'GOOGLE_SIGNUP_EXPIRED');
        case 'conflict': return problem(409, 'GOOGLE_EMAIL_CONFLICT');
        case 'not_allowed': return problem(403, 'GOOGLE_NOT_ALLOWED');
        case 'validation': return problem(422, 'VALIDATION_FAILED');
        case 'network': throw new TypeError('Failed to fetch');
        default:
          refreshCookie = true;
          return json(201, token);
      }
    }
    return problem(404, 'NOT_FOUND');
  });
  vi.stubGlobal('fetch', fetchMock);
  const count = (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path).length;
  return { calls, count };
}

const open = (path: string) => {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

// ================================================================ helpers
describe('google helpers', () => {
  it('builds the backend start URL with an internal return path only', () => {
    expect(googleStartHref('/career/api', '/me/skills')).toBe('/career/api/v1/auth/google/start?return_to=%2Fme%2Fskills');
    expect(googleStartHref('/api', 'https://evil.example/')).toBe('/api/v1/auth/google/start?return_to=%2F');
    expect(googleStartHref('/api', '/', { selectAccount: true })).toContain('prompt=select_account');
  });

  it.each(['/', '/me/skills', '/job-postings?page=2'])('accepts internal path %s', (path) => {
    expect(isSafeAppPath(path)).toBe(true);
  });

  it.each(['', 'https://evil.example', '//evil.example', '/\\evil', '/@evil', '/x/../y', '/%2e%2e/y', '/api/v1/me',
    '/api', '/a\nb', `/${'a'.repeat(600)}`, '/%E0%A4%A'])('rejects unsafe path %s', (path) => {
    expect(isSafeAppPath(path)).toBe(false);
  });

  it('maps the backend next (with app prefix) to a router path', () => {
    expect(nextAppPath('/career/me/skills', '/career')).toBe('/me/skills');
    expect(nextAppPath('/career/', '/career')).toBe('/');
    expect(nextAppPath('/career', '/career')).toBe('/');
    expect(nextAppPath('/church/', '/career')).toBe('/');
    expect(nextAppPath('/careerx/me', '/career')).toBe('/');
    expect(nextAppPath('/career/api/v1/me', '/career')).toBe('/');
    expect(nextAppPath('https://evil.example/', '')).toBe('/');
    expect(nextAppPath(null, '')).toBe('/');
  });

  it('only shows known backend error codes', () => {
    expect(googleLoginError('email_conflict')).toBe(GOOGLE_LOGIN_ERRORS.email_conflict);
    expect(googleLoginError('<script>')).toBeNull();
    expect(googleLoginError('toString')).toBeNull();
    expect(googleLoginError(null)).toBeNull();
  });
});

// ================================================================ login page
describe('login page Google button', () => {
  it('is hidden when the server has Google login off (GET /auth/gate → 404)', async () => {
    const api = backend({ google: 'off' });
    open('/login');
    await screen.findByRole('heading', { name: '로그인' });
    await waitFor(() => expect(api.count('GET', '/v1/auth/gate')).toBe(1));
    expect(screen.queryByRole('link', { name: /Google로 계속하기/ })).not.toBeInTheDocument();
    // 로컬 로그인 화면은 그대로
    expect(screen.getByLabelText(/^이메일/)).toBeInTheDocument();
  });

  it('starts Google login with a full-page link to the backend and ignores repeated clicks', async () => {
    const api = backend();
    open('/login');
    const link = await screen.findByRole('link', { name: 'Google로 계속하기' });
    expect(link).toHaveAttribute('href', '/api/v1/auth/google/start?return_to=%2Faccount');
    // jsdom 은 링크 이동을 하지 않음 → 첫 클릭은 기본 동작 허용, 이후 클릭은 막힘
    const first = fireEvent.click(link);
    expect(first).toBe(true);
    expect(await screen.findByRole('link', { name: 'Google로 이동 중…' })).toHaveAttribute('aria-disabled', 'true');
    expect(fireEvent.click(screen.getByRole('link', { name: 'Google로 이동 중…' }))).toBe(false);
    // 화면은 OAuth 를 fetch 하지 않음(code·토큰을 다루지 않음)
    expect(api.calls.some((c) => c.path.startsWith('/v1/auth/google/start'))).toBe(false);
  });

  it('a gate 401 does not end an existing local session (Google calls use the token-less client)', async () => {
    const api = backend({ refresh: true });
    sessionStorage.setItem('login.sessionAlive', '1'); // 이미 로그인한 브라우저 세션(로컬 로그인)
    open('/account');
    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    await screen.findByRole('button', { name: '완전 로그아웃' }); // gate 401 → 사용 가능
    expect(api.count('POST', '/v1/auth/logout')).toBe(0);
    expect(screen.getByRole('heading', { name: '내 계정' })).toBeInTheDocument();
  });

  it.each(Object.entries(GOOGLE_LOGIN_ERRORS))('shows the %s message from the callback', async (code, message) => {
    backend();
    open(`/login?google_error=${code}`);
    expect(await screen.findByText(message)).toBeInTheDocument();
  });
});

// ================================================================ first sign-up
async function fillGoogleSignup(options: { agree?: boolean; optional?: boolean; name?: string } = {}) {
  expect(await screen.findByText('google.user@example.com')).toBeInTheDocument();
  if (options.name !== undefined) fireEvent.change(screen.getByLabelText(/^이름/), { target: { value: options.name } });
  if (options.agree ?? true) {
    fireEvent.click(screen.getByLabelText(/이용약관 동의 \(필수\)/));
    fireEvent.click(screen.getByLabelText(/개인정보 처리 동의 \(필수\)/));
  }
  if (options.optional) fireEvent.click(screen.getByLabelText(/AI 처리 동의 \(선택\)/));
}

describe('Google first sign-up page', () => {
  it('shows only server-confirmed pending info and lists required/optional policies', async () => {
    backend();
    open('/auth/google/signup');
    await fillGoogleSignup({ agree: false });
    expect(screen.getByLabelText(/^이름/)).toHaveValue('구글 사용자');
    expect(screen.getByLabelText(/이용약관 동의 \(필수\)/)).not.toBeChecked();
    expect(screen.getByLabelText(/AI 처리 동의 \(선택\)/)).toBeInTheDocument();
  });

  it('blocks submit until required policies are agreed (no API call)', async () => {
    const api = backend();
    open('/auth/google/signup');
    await fillGoogleSignup({ agree: false });
    fireEvent.click(screen.getByRole('button', { name: '동의하고 가입' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('필수 약관에 동의해 주세요');
    expect(api.count('POST', '/v1/auth/google/signup')).toBe(0);
  });

  it('sends only display name + consents (no email or sub), logs in and goes home', async () => {
    const api = backend();
    const router = open('/auth/google/signup');
    await fillGoogleSignup({ optional: true, name: '  새 이름  ' });
    fireEvent.click(screen.getByRole('button', { name: '동의하고 가입' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
    const post = api.calls.find((c) => c.method === 'POST' && c.path === '/v1/auth/google/signup');
    expect(post?.body).toEqual({
      display_name: '새 이름',
      consents: [
        { policy_code: 'terms', policy_version: '2026-11', granted: true },
        { policy_code: 'privacy', policy_version: '2026-11', granted: true },
        { policy_code: 'llm_processing', policy_version: '2026-11', granted: true },
      ],
    });
    expect(post?.headers['x-csrf-token']).toBe('1');
    expect(post?.headers.authorization).toBeUndefined();
    expect(JSON.stringify(post?.body)).not.toContain('@');
    expect(sessionStorage.getItem('login.sessionAlive')).toBe('1');
    expect(localStorage.getItem('login.autoLogin')).toBe('1');
    expect(api.count('GET', '/v1/me')).toBe(1);
  });

  it('sends optional policies as not granted unless chosen', async () => {
    const api = backend();
    open('/auth/google/signup');
    await fillGoogleSignup();
    fireEvent.click(screen.getByRole('button', { name: '동의하고 가입' }));
    await waitFor(() => expect(api.count('POST', '/v1/auth/google/signup')).toBe(1));
    const post = api.calls.find((c) => c.path === '/v1/auth/google/signup');
    const consents = (post?.body as { consents: { policy_code: string; granted: boolean }[] } | undefined)?.consents ?? [];
    expect(consents.find((c) => c.policy_code === 'llm_processing')?.granted).toBe(false);
  });

  it('submits once even on a double click', async () => {
    const api = backend();
    open('/auth/google/signup');
    await fillGoogleSignup();
    const button = screen.getByRole('button', { name: '동의하고 가입' });
    fireEvent.submit(button.closest('form')!);
    fireEvent.submit(button.closest('form')!);
    await waitFor(() => expect(api.count('POST', '/v1/auth/google/signup')).toBe(1));
  });

  it.each([
    ['expired', /가입 시간이 지났습니다/, 'Google로 다시 시작'],
    ['conflict', /가입된 계정이 있습니다/, '로그인'],
    ['not_allowed', /사용이 허용되지 않았습니다/, ''],
    ['validation', /필수 약관에 모두 동의했는지/, ''],
  ] as const)('explains a %s response', async (signup, text, link) => {
    backend({ signup });
    open('/auth/google/signup');
    await fillGoogleSignup();
    fireEvent.click(screen.getByRole('button', { name: '동의하고 가입' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(text);
    expect(alert.querySelector('a')?.textContent ?? '').toBe(link);
  });

  it('lets the user retry after a network failure', async () => {
    const api = backend({ signup: 'network' });
    open('/auth/google/signup');
    await fillGoogleSignup();
    fireEvent.click(screen.getByRole('button', { name: '동의하고 가입' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 연결할 수 없습니다');
    fireEvent.click(screen.getByRole('button', { name: '동의하고 가입' }));
    await waitFor(() => expect(api.count('POST', '/v1/auth/google/signup')).toBe(2));
  });

  it.each([
    ['expired', /가입 시간이 지났습니다/],
    ['not_allowed', /사용이 허용되지 않았습니다/],
  ] as const)('explains a %s pending lookup without showing the form', async (pending, text) => {
    backend({ pending });
    open('/auth/google/signup');
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    expect(screen.queryByRole('button', { name: '동의하고 가입' })).not.toBeInTheDocument();
  });
});

// ================================================================ done page + AuthProvider timing
describe('Google done page and session restore', () => {
  it('marks the session kept before the first refresh, so the new session is not logged out (PR #329 bug)', async () => {
    const api = backend({ refresh: true });
    window.history.replaceState({}, '', '/auth/google/done?next=%2Fme%2Fskills');
    const router = open('/auth/google/done?next=%2Fme%2Fskills');
    await waitFor(() => expect(router.state.location.pathname).toBe('/me/skills'));
    expect(api.count('POST', '/v1/auth/refresh')).toBe(1); // 중복 refresh 없음
    expect(api.count('POST', '/v1/auth/logout')).toBe(0); // 방금 받은 세션을 끊지 않음
    expect(sessionStorage.getItem('login.sessionAlive')).toBe('1');
    expect(localStorage.getItem('login.autoLogin')).toBe('1'); // Google 로그인 = 자동 로그인(새 탭에서도 유지)
  });

  it('without the Google marker a plain refresh still follows the existing keep-session rule', async () => {
    const api = backend({ refresh: true });
    open('/account');
    await waitFor(() => expect(api.count('POST', '/v1/auth/logout')).toBe(1)); // 기존 동작(자동 로그인 꺼짐) 유지
  });

  it('a new tab opened by URL keeps a Google session (no auto-logout that would end every tab)', async () => {
    localStorage.setItem('login.autoLogin', '1'); // Google 로그인 뒤 상태(새 탭은 sessionStorage 가 비어 있음)
    const api = backend({ refresh: true });
    open('/account');
    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    expect(api.count('POST', '/v1/auth/logout')).toBe(0);
  });

  it('shows a waiting state instead of protected content while restoring', async () => {
    backend({ refresh: true });
    window.history.replaceState({}, '', '/auth/google/done');
    open('/auth/google/done');
    expect(screen.getByRole('status')).toHaveTextContent('마무리하는 중');
  });

  it('only follows an internal next path', async () => {
    backend({ refresh: true });
    window.history.replaceState({}, '', '/auth/google/done');
    const router = open('/auth/google/done?next=https%3A%2F%2Fevil.example%2F');
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
  });

  it('offers a retry when no session could be restored', async () => {
    backend({ refresh: false });
    window.history.replaceState({}, '', '/auth/google/done');
    open('/auth/google/done');
    expect(await screen.findByRole('alert')).toHaveTextContent('로그인 정보를 확인하지 못했습니다');
    expect(screen.getByRole('link', { name: 'Google로 다시 시도' })).toHaveAttribute(
      'href', '/api/v1/auth/google/start?return_to=%2F');
  });
});

// ================================================================ logout
describe('logout', () => {
  async function signedInAccount() {
    const api = backend({ refresh: true });
    window.history.replaceState({}, '', '/auth/google/done?next=%2Faccount');
    const router = open('/auth/google/done?next=%2Faccount');
    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    return { api, router };
  }

  it('normal logout ends only the app session (no Google signout)', async () => {
    const { api } = await signedInAccount();
    fireEvent.click(screen.getByRole('button', { name: '로그아웃' }));
    await waitFor(() => expect(api.count('POST', '/v1/auth/logout')).toBe(1));
    expect(api.count('POST', '/v1/auth/google/signout')).toBe(0);
  });

  it('full logout calls the CSRF-protected POST and leaves the SPA for the static signed-out page', async () => {
    const assign = vi.spyOn(navigation, 'assign').mockImplementation(() => undefined);
    const { api } = await signedInAccount();
    // 완전 로그아웃 안내는 Google 사용 가능 확인(GET /auth/gate)이 끝난 뒤 그려지므로 기다린다(CI 에서 관찰된 경쟁)
    expect(await screen.findByText(/Google 계정 자체는\s*로그아웃되지 않습니다/)).toBeInTheDocument();
    const refreshBefore = api.count('POST', '/v1/auth/refresh');
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: '완전 로그아웃' }));
    });
    await waitFor(() => expect(assign).toHaveBeenCalledWith('/api/v1/auth/google/signed-out'));
    const post = api.calls.find((c) => c.method === 'POST' && c.path === '/v1/auth/google/signout');
    expect(post?.headers['x-csrf-token']).toBe('1');
    expect(api.count('POST', '/v1/auth/refresh')).toBe(refreshBefore); // 다시 로그인 시도 없음(루프 없음)
    expect(sessionStorage.getItem('login.sessionAlive')).toBeNull();
    expect(localStorage.getItem('login.autoLogin')).toBeNull(); // 완전 로그아웃은 자동 로그인도 해제
  });

  it('hides full logout when Google login is off', async () => {
    const api = backend({ google: 'off', refresh: true });
    window.history.replaceState({}, '', '/auth/google/done?next=%2Faccount');
    open('/auth/google/done?next=%2Faccount');
    expect(await screen.findByRole('heading', { name: '내 계정' })).toBeInTheDocument();
    // 가용성 확인(404)이 끝난 뒤에도 버튼이 없어야 한다(확인 전 '아직 없음'으로 통과하지 않도록)
    await waitFor(() => expect(api.count('GET', '/v1/auth/gate')).toBeGreaterThan(0));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByRole('button', { name: '로그아웃' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '완전 로그아웃' })).not.toBeInTheDocument();
  });
});
