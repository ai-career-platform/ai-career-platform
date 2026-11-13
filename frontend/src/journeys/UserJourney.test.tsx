/**
 * T92 사용자 여정·내비게이션 정합성 — 실제 라우터(buildRoutes) + Mock HTTP, **링크·메뉴 클릭으로만** 이동합니다.
 * Mock 응답이므로 실제 API 연동 PASS 가 아닙니다. 권한 우회나 가짜 성공 처리 없이 기존 인증(RequireAuth)을 그대로 씁니다.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { buildRoutes } from '../routes';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: true } }));

function open(path: string) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: true }), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

async function login(email = 'user@example.com') {
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

const h1 = (name: string | RegExp) => screen.findByRole('heading', { level: 1, name }, { timeout: 4000 });
const click = async (name: string | RegExp) => fireEvent.click(await screen.findByRole('link', { name }));

describe('main journey: sign in → profile → skills → target roles → explore → recommendations → saved postings', () => {
  it('every step is reachable by clicking links and menus only', async () => {
    const router = open('/');
    await click('로그인');
    await h1(/로그인/);
    await login();
    await h1('내 계정');                                  // 로그인 후 기본 목적지
    await click('나의 기술 관리');
    await h1('나의 기술');
    await act(() => router.navigate(-1));                  // 뒤로가기
    await h1('내 계정');
    await click('목표 직무 설정');                        // T92 에서 추가한 진입점
    await h1('목표 직무 관리');
    await click('직무·기술 탐색');
    await h1('어떤 일이 나와 맞을까요?');
    await click('기업·채용공고 탐색');
    await h1('새로운 기회를 찾아보세요');
    await click('맞춤 추천');
    await h1('맞춤 공고 추천');
    await click('일반 사용자');                            // 헤더의 계정 링크
    await h1('내 계정');
    await click('저장한 공고');                            // 지원 준비 = 현재는 저장한 공고까지
    await h1('저장한 채용공고');
    // 빈 결과면 안내 문구, 아니면 목록 — 둘 중 하나가 반드시 보여야 함(로딩에서 멈추지 않음)
    await waitFor(() => expect(Boolean(screen.queryByText('저장한 공고가 없습니다.')) || screen.queryAllByRole('listitem').length > 0).toBe(true));
    await click('일반 사용자');
    await click('경력·프로젝트 관리');
    await h1('경력·프로젝트');
    expect(router.state.location.pathname).toBe('/me/career-history');
  });
});

describe('interruptions and access control', () => {
  it('a protected deep link sends a visitor to login and resumes the same screen afterwards', async () => {
    const router = open('/me/bookmarks');
    await h1(/로그인/);
    await login();
    await h1('저장한 채용공고');
    expect(router.state.location.pathname).toBe('/me/bookmarks');
  });

  it('after logout, going back to a protected screen asks for login again', async () => {
    const router = open('/login');
    await login();
    await h1('내 계정');
    fireEvent.click(screen.getByRole('button', { name: '로그아웃' }));
    await act(() => router.navigate('/me/skills'));
    await h1(/로그인/);
    expect(router.state.location.pathname).toBe('/login');
  });

  it('a job seeker opening an admin screen gets the 403 page with a way home', async () => {
    const router = open('/login');
    await login();
    await h1('내 계정');
    await act(() => router.navigate('/admin/audit-events'));
    await h1('접근 권한이 없습니다');
    expect(screen.queryByRole('link', { name: '운영 감사 (Mock)' })).not.toBeInTheDocument();
    await click('홈으로 이동');
    expect(router.state.location.pathname).toBe('/');
  });

  it('an unknown URL shows 404 with a way home and the main menu', async () => {
    const router = open('/no/such/screen');
    await h1('페이지를 찾을 수 없습니다');
    expect(screen.getByRole('navigation', { name: '주 메뉴' })).toBeInTheDocument();
    await click('홈으로 이동');
    expect(router.state.location.pathname).toBe('/');
  });

  it('the sign-up link is no longer a gap: /signup opens the sign-up screen, not 404', async () => {
    const router = open('/signup');
    expect(await h1('회원가입')).toBeInTheDocument();
    expect(screen.queryByText('페이지를 찾을 수 없습니다')).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/signup');
  });

  it('the password-reset link is no longer a gap after T94 (#196)', async () => {
    open('/password-reset');
    expect(await screen.findByRole('heading', { level: 1 })).not.toHaveTextContent('페이지를 찾을 수 없습니다');
  });
});

// ---------------------------------------------------------------- static navigation gate
const SRC = resolve(cwd(), 'src');
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [path] : [];
  });
}
// 쿼리 문자열이 붙은 링크(`/company/postings?org=${id}`)도 경로 부분을 진입점으로 셉니다(T127)
const LINK = /(?:to|href)=\{?["'`](\/[A-Za-z0-9/_:#-]*)["'`?]/g;
const linkTargets = () => new Set(sources(SRC).flatMap((file) => [...readFileSync(file, 'utf8').matchAll(LINK)].map((m) => m[1]!)));
function routePaths(): string[] {
  const text = readFileSync(join(SRC, 'routes.tsx'), 'utf8');
  return [...text.matchAll(/path: '([^']+)'/g)].map((m) => '/' + m[1]!.replace(/^\//, ''));
}
const matches = (route: string, link: string) =>
  new RegExp('^' + route.replace(/:[^/]+/g, '[^/]+').replace(/\/$/, '') + '/?$').test(link.replace(/\/$/, '') || '/');

// 알려진 공백(문서 T92 §4): 화면이 아직 없음 → 고쳐지면 이 목록에서 지워야 시험이 통과
const KNOWN_DEAD_LINKS = new Set<string>();
// 앱 안 진입점이 없어도 되는 경로(사유): 운영 점검·개발 미리보기·상세(목록에서 동적 링크)·404·
// 메일 링크로만 들어오는 화면(T124 기업 초대 수락 — 링크는 `#token=` fragment, Mock 메일함의 동적 링크)
const NO_ENTRY_NEEDED = new Set(['/system-status', '/*', '/admin/moderation/:caseId', '/company-invitations/accept', '/p/:token']);

describe('navigation gate', () => {
  it('every in-app link points to a defined route (except the pinned known gaps)', () => {
    const routes = routePaths();
    const dead = [...linkTargets()].filter((link) => !link.startsWith('/#') && !routes.some((r) => matches(r, link)));
    expect(new Set(dead)).toEqual(KNOWN_DEAD_LINKS);
  });

  it('every defined screen has at least one in-app entry point', () => {
    const links = [...linkTargets()];
    const orphans = routePaths().filter((r) => r !== '/' && !NO_ENTRY_NEEDED.has(r) && !links.some((l) => matches(r, l)));
    expect(orphans).toEqual([]);
  });
});
