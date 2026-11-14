/**
 * T124 기업 콘솔 — 실제 라우터(buildRoutes) + Mock HTTP 로그인 + 기업 Mock Adapter(T123 규칙 흉내).
 * 여기서는 Mock 모드 화면 흐름만 봅니다(Mock PASS 이며 실제 API PASS 아님). 실제 API 경로는
 * company/CompanyServiceProvider.test.tsx·api/companyAccounts.test.ts, 서버는 test_t123_company_accounts_postgres.py.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { explain } from '../company/companyErrors';
import { MOCK_PASSWORD } from '../mocks/handlers';
import type { MockCompanyBackend, MockCompanyOptions } from '../mocks/companyAccounts';
import { buildRoutes } from '../routes';

const holder = vi.hoisted(() => ({ backend: null as MockCompanyBackend | null }));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false, companyConsoleUi: false } }));
vi.mock('../mocks/companyAccounts', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/companyAccounts')>();
  return {
    ...original,
    createMockCompanyBackend: (options: MockCompanyOptions = {}) => {
      holder.backend ??= original.createMockCompanyBackend({ ...options, latencyMs: 0 });
      return holder.backend;
    },
  };
});

const USER = 'user@example.com';
const ADMIN = 'admin@example.com';
beforeEach(() => { holder.backend = null; });

async function open(path: string, as?: string, companyConsoleUi = true) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: false, companyConsoleUi }),
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
const orgButton = (name: RegExp) => screen.findByRole('button', { name });
const membersTable = () => screen.findByRole('table', { name: /조직 멤버/ });
const orgIdOf = (name: string) => holder.backend!.snapshot().orgs.find((o) => o.name === name)!.organization_id;

describe('feature flag and access', () => {
  it('flag off: no menu and the URL is not found', async () => {
    await open('/company', USER, false);
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '기업 콘솔 (Mock)' })).not.toBeInTheDocument();
  });

  it('default routes keep it off; the flag alone opens it and the provider uses the mock only in mock mode', async () => {
    const { routes } = await import('../routes');
    expect(JSON.stringify(routes, (k, v) => (k === 'element' ? undefined : v))).not.toContain("company");
    const envText = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    expect(envText).toContain("companyConsoleUi: import.meta.env.VITE_COMPANY_CONSOLE_UI === 'true',");
    // T127 공고 콘솔은 아직 Mock 전용(T125 저장소 없음)
    expect(envText).toContain("companyPostingsUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_COMPANY_CONSOLE_UI === 'true'");
    const provider = readFileSync(resolve(cwd(), 'src/company/CompanyServiceProvider.tsx'), 'utf8');
    expect(provider).toContain('env.mockEnabled ? createMockCompanyBackend');
    expect(provider).toContain('api.companyAccounts');
    expect(provider).not.toMatch(/fetch\(/);
  });

  it('anonymous users go to login; signed-in users see the menu', async () => {
    await open('/company');
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
    cleanup();
    await open('/company', USER);
    expect(await screen.findByRole('link', { name: '기업 콘솔 (Mock)' })).toBeInTheDocument();
  });
});

describe('owner console', () => {
  it('lists my organizations with role and status, and shows masked members and invitations', async () => {
    await open('/company', USER);
    expect(await screen.findByText(/기업 관리자 · 활성/)).toBeInTheDocument();
    expect(screen.getByText(/기업 담당자 · 활성/)).toBeInTheDocument();
    expect(screen.getByText(/기업 관리자 · 운영 확인 대기/)).toBeInTheDocument();
    fireEvent.click(await orgButton(/가상테크/));
    const table = await membersTable();
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(table.textContent).toContain('s***@example.invalid');
    expect(table.textContent).not.toContain('staff.a@example.invalid');
    expect(await screen.findByText('p***@example.invalid')).toBeInTheDocument();
    expect(screen.getByText('만료')).toBeInTheDocument();
    expect(screen.getAllByText(/재전송 \d\/5/)).toHaveLength(2);
  });

  it('invites, rejects duplicates, and the invitee accepts from the fragment link (token removed from the URL)', async () => {
    await open(`/company?org=${'pending'}`, USER);
    fireEvent.click(await orgButton(/가상테크/));
    fireEvent.change(await screen.findByLabelText('초대할 이메일'), { target: { value: ADMIN } });
    fireEvent.click(screen.getByRole('button', { name: '초대 보내기' }));
    expect(await screen.findByRole('status')).toHaveTextContent('admin@example.com 주소로 초대를 보냈습니다');
    const link = holder.backend!.lastInviteLink()!;
    expect(link).toMatch(/^\/company-invitations\/accept#token=/);
    expect(screen.getByRole('link', { name: '초대 링크 열기' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('초대할 이메일'), { target: { value: ADMIN } });
    fireEvent.click(screen.getByRole('button', { name: '초대 보내기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('이미 초대했거나 이미 멤버인 이메일입니다.');
    cleanup();

    const router = await open(link, ADMIN);
    await waitFor(() => expect(router.state.location.hash).toBe(''));
    fireEvent.click(await screen.findByRole('button', { name: '초대 수락' }));
    expect(await screen.findByRole('status')).toHaveTextContent('가상테크 (Mock)에 기업 담당자(으)로 합류했습니다.');
  });

  it('a link sent to someone else, a revoked link and a rotated link all fail with one message', async () => {
    await open('/company', USER);
    fireEvent.click(await orgButton(/가상테크/));
    fireEvent.change(await screen.findByLabelText('초대할 이메일'), { target: { value: ADMIN } });
    fireEvent.click(screen.getByRole('button', { name: '초대 보내기' }));
    await screen.findByRole('status');
    const first = holder.backend!.lastInviteLink()!;
    fireEvent.click(await screen.findByRole('button', { name: 'a***@example.com 초대 재전송' }));
    expect(await screen.findByRole('status')).toHaveTextContent('이전 링크는 더 이상 쓸 수 없습니다');
    cleanup();
    await open(first, ADMIN);
    fireEvent.click(await screen.findByRole('button', { name: '초대 수락' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('초대가 만료되었거나, 취소되었거나');
    cleanup();
    await open(holder.backend!.lastInviteLink()!, USER);                 // 다른 계정
    fireEvent.click(await screen.findByRole('button', { name: '초대 수락' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('초대가 만료되었거나, 취소되었거나');
  });

  it('revokes a pending invitation', async () => {
    await open('/company', USER);
    fireEvent.click(await orgButton(/가상테크/));
    fireEvent.click(await screen.findByRole('button', { name: 'p***@example.invalid 초대 취소' }));
    expect(await screen.findByRole('status')).toHaveTextContent('초대를 취소했습니다.');
    expect(await screen.findByText('취소됨')).toBeInTheDocument();
  });

  it('the last owner cannot demote themselves (409) and the table reloads the real role', async () => {
    await open('/company', USER);
    fireEvent.click(await orgButton(/가상테크/));
    await membersTable();
    fireEvent.change(screen.getByLabelText('일반 사용자 역할'), { target: { value: 'member' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('마지막 기업 관리자는 내리거나 제외할 수 없습니다');
    await waitFor(() => expect((screen.getByLabelText('일반 사용자 역할') as HTMLSelectElement).value).toBe('owner'));
  });

  it('promotes and removes a member after confirmation; access is gone right away', async () => {
    await open('/company', USER);
    fireEvent.click(await orgButton(/가상테크/));
    await membersTable();
    fireEvent.change(screen.getByLabelText('가상 담당자 A 역할'), { target: { value: 'owner' } });
    expect(await screen.findByRole('status')).toHaveTextContent('가상 담당자 A: 기업 관리자(으)로 바꿨습니다.');
    fireEvent.click(screen.getByRole('button', { name: '가상 담당자 A 제외' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '제외' }));
    expect(await screen.findByRole('status')).toHaveTextContent('권한은 바로 사라집니다');
    const orgId = orgIdOf('가상테크 (Mock)');
    await expect(holder.backend!.serviceFor('staff.a@example.invalid').organization(orgId)).rejects.toMatchObject({ status: 404 });
  });

  it('pending organization: invitations are disabled with a reason', async () => {
    await open('/company', USER);
    fireEvent.click(await orgButton(/검증대기랩/));
    expect((await screen.findAllByRole('note')).map((n) => n.textContent).join(' ')).toContain('운영 확인 대기 중입니다');
    expect(screen.getByLabelText('초대할 이메일')).toBeDisabled();
    expect(screen.getByRole('button', { name: '초대 보내기' })).toBeDisabled();
  });

  it('registers a new organization as pending and selects it', async () => {
    await open('/company', USER);
    fireEvent.change(await screen.findByLabelText('회사 이름'), { target: { value: '새회사 (Mock)' } });
    fireEvent.click(screen.getByRole('button', { name: '등록 신청' }));
    expect(await screen.findByRole('heading', { name: /새회사 \(Mock\)/ })).toBeInTheDocument();
    expect(screen.getByText(/운영 확인 대기 중입니다/)).toBeInTheDocument();
  });
});

describe('member view, outsiders and errors', () => {
  it('a member sees no invitations or role controls and can leave', async () => {
    const router = await open('/company', USER);
    fireEvent.click(await orgButton(/예시소프트/));
    const table = await membersTable();
    expect(within(table).queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '초대' })).not.toBeInTheDocument();
    expect(screen.getByText('초대·역할 변경은 기업 관리자만 할 수 있습니다.')).toBeInTheDocument();
    expect(within(table).queryByRole('button', { name: /제외/ })).not.toBeInTheDocument();
    fireEvent.click(within(table).getByRole('button', { name: '이 조직에서 나가기' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '나가기' }));
    await waitFor(() => expect(router.state.location.search).toBe(''));
    await waitFor(() => expect(screen.queryByRole('button', { name: /예시소프트/ })).not.toBeInTheDocument());
  });

  it("another company's organization id shows not-found, not its data", async () => {
    await open('/company', ADMIN);
    await screen.findByText('소속된 조직이 없습니다.');
    cleanup();
    await open(`/company?org=${orgIdOf('가상테크 (Mock)')}`, ADMIN);
    expect(await screen.findByText('조직을 찾을 수 없거나 접근 권한이 없습니다')).toBeInTheDocument();
    expect(screen.queryByText('가상 담당자 A')).not.toBeInTheDocument();
    await expect(holder.backend!.serviceFor(ADMIN).members(orgIdOf('가상테크 (Mock)'))).rejects.toMatchObject({ status: 404 });
    await expect(holder.backend!.serviceFor(USER).invitations(orgIdOf('예시소프트 (Mock)'))).rejects.toMatchObject({ status: 403 });
  });

  it('load failure shows retry', async () => {
    await open('/company', USER);
    await screen.findByText(/기업 관리자 · 활성/);
    cleanup();
    holder.backend!.failNext('load');
    await open('/company', USER);
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText(/기업 관리자 · 활성/)).toBeInTheDocument();
  });

  it('maps server errors to specific messages', () => {
    expect(explain(new ApiError(403, '/x', undefined, 'FORBIDDEN'), 'role')).toBe('이 작업은 기업 관리자만 할 수 있습니다.');
    expect(explain(new ApiError(403, '/x', undefined, 'FORBIDDEN'), 'invite')).toContain('운영 확인이 끝난 조직');
    expect(explain(new ApiError(404, '/x'), 'remove')).toContain('접근 권한이 없습니다');
    expect(explain(new ApiError(409, '/x'), 'resend')).toContain('재전송 횟수');
    expect(explain(new ApiError(0, '/x'), 'invite')).toContain('서버에 연결하지 못했습니다');
  });
});
