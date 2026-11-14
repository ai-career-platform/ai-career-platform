/**
 * T130 공개 포트폴리오 편집·미리보기·공유 — 실제 라우터(buildRoutes) + Mock HTTP 로그인 + 포트폴리오 Mock Adapter.
 * 여기서는 Mock 모드 화면 흐름만 봅니다(Mock PASS 이며 실제 API PASS 아님). 실제 API 경로는
 * portfolio/PortfolioServiceProvider.test.tsx·api/publicPortfolio.test.ts, 서버는 test_t129_public_portfolio_postgres.py.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import type { MockPortfolioBackend, MockPortfolioOptions } from '../mocks/publicPortfolio';
import { buildRoutes } from '../routes';

const holder = vi.hoisted(() => ({ backend: null as MockPortfolioBackend | null }));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false, publicPortfolioUi: false } }));
vi.mock('../mocks/publicPortfolio', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/publicPortfolio')>();
  return {
    ...original,
    createMockPortfolioBackend: (options: MockPortfolioOptions = {}) => {
      holder.backend ??= original.createMockPortfolioBackend({ ...options, latencyMs: 0 });
      return holder.backend;
    },
  };
});

const USER = 'user@example.com';
beforeEach(() => { holder.backend = null; });

async function open(path: string, as?: string, publicPortfolioUi = true) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: false, publicPortfolioUi }),
    { initialEntries: [as ? '/login' : path] });
  render(<RouterProvider router={router} />);
  if (as) {
    fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: as } });
    fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await screen.findByRole('heading', { name: '내 계정' });
    await act(() => router.navigate(path));
  }
  return router;
}
const check = (label: string | RegExp) => fireEvent.click(screen.getByRole('checkbox', { name: label }));
const preview = () => screen.getByRole('heading', { name: /2\. 미리보기/ }).closest('section')!;

async function publish(router: Awaited<ReturnType<typeof open>>) {
  await screen.findByRole('heading', { name: /1\. 공개할 항목/ });
  check('한 줄 소개'); check('회사·기관'); check('직무·직함'); check('기간(연·월)'); check(/경력: 가상테크/);
  fireEvent.click(screen.getByRole('button', { name: '선택 저장' }));
  expect(await screen.findByRole('status')).toHaveTextContent('선택을 저장했습니다');
  fireEvent.click(await screen.findByRole('button', { name: '이대로 공개 확정' }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByRole('button', { name: '공개 확정' })).toBeDisabled();
  fireEvent.click(within(dialog).getByRole('checkbox', { name: '위 내용을 이해했습니다' }));
  fireEvent.click(within(dialog).getByRole('button', { name: '공개 확정' }));
  expect(await screen.findByText('공개 확정됨')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '공유 링크 만들기' }));
  const url = (await screen.findByLabelText('공유 주소') as HTMLInputElement).value;
  return { router, path: new URL(url).pathname };
}

describe('feature flag and access', () => {
  it('flag off: no menu and the URLs are not found', async () => {
    await open('/me/public-profile', USER, false);
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '공개 포트폴리오 (Mock)' })).not.toBeInTheDocument();
  });

  it('default routes keep it off; the flag alone opens it and the provider uses the mock only in mock mode', async () => {
    const { routes } = await import('../routes');
    const json = JSON.stringify(routes, (k, v) => (k === 'element' ? undefined : v));
    expect(json).not.toContain('public-profile');
    expect(json).not.toContain('p/:token');
    expect(readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8'))
      .toContain("publicPortfolioUi: import.meta.env.VITE_PUBLIC_PORTFOLIO_UI === 'true',");
    const provider = readFileSync(resolve(cwd(), 'src/portfolio/PortfolioServiceProvider.tsx'), 'utf8');
    expect(provider).toContain('env.mockEnabled ? createMockPortfolioBackend');
    expect(provider).toContain('api.publicPortfolio');
    expect(provider).not.toMatch(/fetch\(/);
  });

  it('settings need login, the public page does not (and an unknown link is a generic error)', async () => {
    await open('/me/public-profile');
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
    cleanup();
    await open(`/p/${'x'.repeat(44)}`);
    expect(await screen.findByText('볼 수 없는 링크입니다')).toBeInTheDocument();
  });
});

describe('private by default and confirmed publishing', () => {
  it('starts private: empty preview, no confirm, no links, and lists what can never be public', async () => {
    await open('/me/public-profile', USER);
    expect(await screen.findByText('공개하는 항목이 없습니다(비공개).')).toBeInTheDocument();
    expect(screen.getByText('비공개')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '이대로 공개 확정' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '공유 링크 만들기' })).toBeDisabled();
    expect(screen.getByText(/공개할 수 없는 항목: 이메일·연락처, 이력서 등 업로드 문서, AI 분석·적합도 결과/)).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox').every((c) => !(c as HTMLInputElement).checked)).toBe(true);
  });

  it('preview equals the public page, shows only selected items, and the page is noindex', async () => {
    const { router, path } = await publish(await open('/me/public-profile', USER));
    await waitFor(() => expect(preview().textContent).toContain('가상테크 · 백엔드 개발자'));
    const shown = preview().textContent!;
    expect(shown).toContain('2023-03 ~ 2025-01');
    for (const hidden of ['비공개로 둘 회사', '010-0000-0000', USER, '서울 강남구', '추천 시스템', 'Python']) expect(shown).not.toContain(hidden);
    expect(screen.getByText('이 주소는 지금 한 번만 보여 줍니다.')).toBeInTheDocument();
    await act(() => router.navigate(path));
    const view = (await screen.findByRole('heading', { name: '경력' })).closest('article')!;
    expect(view.textContent).toContain('가상테크 · 백엔드 개발자');
    expect(view.textContent).not.toContain('비공개로 둘 회사');
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex, nofollow, noarchive');
    expect(document.head.querySelector('meta[name="referrer"]')?.getAttribute('content')).toBe('no-referrer');
  });

  it('alias replaces the real name', async () => {
    await open('/me/public-profile', USER);
    await screen.findByRole('heading', { name: /1\. 공개할 항목/ });
    check('이름(또는 별칭)');
    fireEvent.change(screen.getByRole('textbox', { name: /별칭\(비우면/ }), { target: { value: '백엔드 K' } });
    fireEvent.click(screen.getByRole('button', { name: '선택 저장' }));
    await waitFor(() => expect(preview().textContent).toContain('백엔드 K'));
    expect(preview().textContent).not.toContain('일반 사용자');
  });
});

describe('revocation, re-confirmation and live data', () => {
  it('revoking a link closes it immediately', async () => {
    const { router, path } = await publish(await open('/me/public-profile', USER));
    fireEvent.click(await screen.findByRole('button', { name: /링크 회수/ }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '회수' }));
    expect(await screen.findByRole('status')).toHaveTextContent('링크를 회수했습니다');
    expect(await screen.findByText(/회수됨/)).toBeInTheDocument();
    await act(() => router.navigate(path));
    expect(await screen.findByText('볼 수 없는 링크입니다')).toBeInTheDocument();
  });

  it('changing the selection closes existing links until confirmed again', async () => {
    const { router, path } = await publish(await open('/me/public-profile', USER));
    check('보유 기술');
    fireEvent.click(screen.getByRole('button', { name: '선택 저장' }));
    expect(await screen.findByText('공개 확인 전(링크가 열리지 않음)')).toBeInTheDocument();
    await act(() => router.navigate(path));
    expect(await screen.findByText('볼 수 없는 링크입니다')).toBeInTheDocument();
  });

  it('withdrawing closes every link and resets the selection', async () => {
    const { router, path } = await publish(await open('/me/public-profile', USER));
    fireEvent.click(screen.getByRole('button', { name: '공개 중단(동의 철회)' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '공개 중단' }));
    expect(await screen.findByRole('status')).toHaveTextContent('공개를 중단했습니다');
    await waitFor(() => expect(screen.getAllByRole('checkbox').every((c) => !(c as HTMLInputElement).checked)).toBe(true));
    expect(screen.getByText('공개하는 항목이 없습니다(비공개).')).toBeInTheDocument();
    await act(() => router.navigate(path));
    expect(await screen.findByText('볼 수 없는 링크입니다')).toBeInTheDocument();
  });

  it('the public page renders current data: edits and deletions show at once, new items stay private', async () => {
    const { router, path } = await publish(await open('/me/public-profile', USER));
    holder.backend!.editProfile(USER, (p) => {
      p.headline = '새 한 줄 소개';
      p.experiences = [{ id: 'exp-9', organization: '새 회사', title: '리드', start: '2025-02', end: null, description: null }];
    });
    await act(() => router.navigate(path));
    expect(await screen.findByText('새 한 줄 소개')).toBeInTheDocument();
    expect(screen.queryByText(/가상테크/)).not.toBeInTheDocument();
    expect(screen.queryByText(/새 회사/)).not.toBeInTheDocument();
  });

  it('at most three active links; failures keep the previous state', async () => {
    await publish(await open('/me/public-profile', USER));
    for (const expected of [2, 3]) {
      await waitFor(() => expect(screen.getByRole('button', { name: '공유 링크 만들기' })).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: '공유 링크 만들기' }));
      await waitFor(() => expect(screen.getAllByText(/사용 중/)).toHaveLength(expected));
    }
    expect(screen.getByRole('button', { name: '공유 링크 만들기' })).toBeDisabled();
    holder.backend!.failNext('mutate');
    check('보유 기술');
    fireEvent.click(screen.getByRole('button', { name: '선택 저장' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 연결하지 못했습니다');
    expect(await screen.findByText('공개 확정됨')).toBeInTheDocument();   // 실패한 저장은 확인 상태를 바꾸지 않음
  });
});
