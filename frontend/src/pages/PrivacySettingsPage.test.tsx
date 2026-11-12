import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import { RequireAuth } from '../auth/RequireAuth';
import { mockHttp, type RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { resetPrivacyMocks } from '../mocks/privacy';
import { PrivacySettingsPage } from './PrivacySettingsPage';

const mode = vi.hoisted(() => ({ mock: true }));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', get mockEnabled() { return mode.mock; } } }));

const user = mockHttp('mock-access-user@example.com');
const viaMock: RequestFn = (path, options) => user.request(path, options);

function show(anonymous = false, customRequest?: RequestFn) {
  const request = vi.fn<RequestFn>(customRequest ?? viaMock);
  const value: AuthContextValue = {
    state: anonymous ? { status: 'anonymous' } : { status: 'authenticated', token: 'mock-access-user@example.com',
      user: { email: 'user@example.com', displayName: '합성 사용자', roles: ['job_seeker'] } },
    login: vi.fn<AuthContextValue['login']>().mockResolvedValue(undefined), logout: vi.fn<AuthContextValue['logout']>().mockResolvedValue(undefined), signup: vi.fn<AuthContextValue['signup']>(),
  };
  render(<AuthContext.Provider value={value}><WithApi request={request}><MemoryRouter initialEntries={['/account/privacy']}>
    <Routes><Route element={<Outlet />}><Route element={<RequireAuth />}>
      <Route path="/account/privacy" element={<PrivacySettingsPage />} />
    </Route><Route path="/login" element={<h1>로그인 필요</h1>} /></Route></Routes>
  </MemoryRouter></WithApi></AuthContext.Provider>);
  return request;
}

beforeEach(() => { resetPrivacyMocks(); mode.mock = true; });

async function ready() { await screen.findByRole('article', { name: 'AI 처리' }); }

describe('T32 privacy settings (Mock, not PostgreSQL evidence)', () => {
  it('protects the page with existing RequireAuth', async () => {
    const request = show(true);
    expect(await screen.findByRole('heading', { name: '로그인 필요' })).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });

  it('loads own consent cards, policy metadata and no required change button', async () => {
    show(); expect(screen.getByText('개인정보 설정을 불러오는 중')).toBeInTheDocument();
    await ready();
    const required = screen.getByRole('article', { name: '이용약관' });
    expect(within(required).getByText('필수')).toBeInTheDocument();
    expect(within(required).queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getAllByText(/2026-11/).length).toBeGreaterThan(0);
    expect(screen.getByText('진행 중인 탈퇴 요청이 없습니다.')).toBeInTheDocument();
    expect(screen.getByText(/실제 PostgreSQL/)).toBeInTheDocument();
  });

  it('does not call POST when withdrawal confirmation is cancelled', async () => {
    const request = show(); await ready();
    fireEvent.click(within(screen.getByRole('article', { name: 'AI 처리' })).getByRole('button', { name: '철회' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/관련 기능/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '돌아가기' }));
    expect(request.mock.calls.filter(([,o]) => o?.method === 'POST')).toHaveLength(0);
  });

  it('records optional consent and withdrawal only after confirmation', async () => {
    const request = show(); await ready();
    fireEvent.click(within(screen.getByRole('article', { name: '행동 기록' })).getByRole('button', { name: '동의' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '변경 확인' }));
    await screen.findByText('동의 상태를 저장했습니다.');
    expect(request).toHaveBeenCalledWith('/v1/me/consents', expect.objectContaining({ body: expect.objectContaining({ policy_code: 'behavior_tracking', granted: true }) }));
    fireEvent.click(within(screen.getByRole('article', { name: 'AI 처리' })).getByRole('button', { name: '철회' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '변경 확인' }));
    await waitFor(() => expect(within(screen.getByRole('article', { name: 'AI 처리' })).getByText('철회')).toBeInTheDocument());
  });

  it('requires exact DELETE and prevents duplicate deletion clicks', async () => {
    const request = show(); await ready();
    fireEvent.click(screen.getByRole('button', { name: '회원 탈퇴 요청' }));
    const dialog = screen.getByRole('dialog');
    const submit = within(dialog).getByRole('button', { name: '탈퇴 요청 접수' });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('확인 문구'), { target: { value: 'delete' } });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('확인 문구'), { target: { value: 'DELETE' } });
    fireEvent.click(submit); fireEvent.click(submit);
    await screen.findByText('탈퇴 요청을 접수했습니다.');
    expect(request.mock.calls.filter(([path,o]) => path === '/v1/me/deletion-request' && o?.method === 'POST')).toHaveLength(1);
    expect(screen.getByText('접수됨')).toBeInTheDocument();
    expect(screen.getByText('삭제 예정일은 아직 정해지지 않았습니다.')).toBeInTheDocument();
  });

  it('shows pending request and supports cancellation only in Mock mode', async () => {
    await user.request('/v1/me/deletion-request', { method: 'POST', body: { confirmation: 'DELETE' } });
    const request = show(); await ready();
    fireEvent.click(screen.getByRole('button', { name: '요청 취소 (Mock)' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '취소 확인' }));
    await screen.findByText('탈퇴 요청이 취소됐습니다.');
    expect(request).toHaveBeenCalledWith('/v1/me/deletion-request', expect.objectContaining({ method: 'DELETE' }));
  });

  it('does not expose an unsupported real cancellation button', async () => {
    mode.mock = false;
    await user.request('/v1/me/deletion-request', { method: 'POST', body: { confirmation: 'DELETE' } });
    show(); await ready();
    expect(screen.queryByRole('button', { name: /요청 취소/ })).not.toBeInTheDocument();
    expect(screen.getByText(/현재 실제 탈퇴 취소는 지원하지 않습니다/)).toBeInTheDocument();
  });

  it('keeps confirmation input and existing cards when a mutation fails', async () => {
    show(false, (path, options = {}) => options.method === 'POST'
      ? Promise.reject(new Error('synthetic failure'))
      : viaMock(path, options));
    await ready();
    fireEvent.click(screen.getByRole('button', { name: '회원 탈퇴 요청' }));
    fireEvent.change(screen.getByLabelText('확인 문구'), { target: { value: 'DELETE' } });
    fireEvent.click(screen.getByRole('button', { name: '탈퇴 요청 접수' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('처리하지 못했습니다');
    expect(within(screen.getByRole('dialog')).getByRole('alert')).toHaveTextContent('처리하지 못했습니다');
    const failedDialog = screen.getByRole('dialog');
    failedDialog.focus();
    fireEvent.keyDown(failedDialog, { key: 'Tab', shiftKey: true });
    expect(within(failedDialog).getByRole('button', { name: '돌아가기' })).toHaveFocus();
    expect(screen.getByLabelText('확인 문구')).toHaveValue('DELETE');
    expect(screen.getByRole('article', { name: 'AI 처리' })).toBeInTheDocument();
  });


  it('keeps focus inside a pending modal with no enabled controls', async () => {
    let finish!: (value: unknown) => void;
    show(false, (path, options = {}) => options.method === 'POST'
      ? new Promise(resolve => { finish = resolve; })
      : viaMock(path, options));
    await ready();
    fireEvent.click(within(screen.getByRole('article', { name: 'AI 처리' })).getByRole('button'));
    fireEvent.click(screen.getByRole('button', { name: '변경 확인' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveFocus();
    expect(fireEvent.keyDown(dialog, { key: 'Tab', cancelable: true })).toBe(false);
    expect(dialog).toHaveFocus();
    finish({ consent_id: 'synthetic', policy_code: 'llm_processing', policy_version: '2026-11', granted: false, recorded_at: new Date().toISOString() });
    await screen.findByText('동의 상태를 저장했습니다.');
  });

  it('keeps Mock users isolated and rejects anonymous access', async () => {
    await user.request('/v1/me/consents', { method: 'POST', body: { policy_code: 'llm_processing', policy_version: '2026-11', granted: false } });
    const admin = await mockHttp('mock-access-admin@example.com').request<Array<{policy_code:string;granted:boolean}>>('/v1/me/consents');
    expect(admin.find(c => c.policy_code === 'llm_processing')?.granted).toBe(true);
    await expect(mockHttp().request('/v1/me/consents')).rejects.toMatchObject({ status: 401 });
  });
});
