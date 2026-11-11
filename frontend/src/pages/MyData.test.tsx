/**
 * T143 내 데이터 내려받기·요청 이력 — 실제 라우터(buildRoutes) + Mock HTTP 로그인 + 반출 Mock Adapter.
 * 실제 API(T142)는 기능 플래그 뒤·저장소 없음이라 연결하지 않았습니다(Mock PASS 이며 실제 API PASS 아님).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import type { MockPersonalDataBackend, MockPersonalDataOptions } from '../mocks/personalData';
import { buildRoutes } from '../routes';

const holder = vi.hoisted(() => ({ backend: null as MockPersonalDataBackend | null, now: Date.parse('2026-11-11T03:00:00Z') }));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false, personalDataUi: false } }));
vi.mock('../mocks/personalData', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/personalData')>();
  return {
    ...original,
    createMockPersonalDataBackend: (options: MockPersonalDataOptions = {}) => {
      holder.backend ??= original.createMockPersonalDataBackend({ ...options, latencyMs: 0, processingMs: 60_000, now: () => new Date(holder.now) });
      return holder.backend;
    },
  };
});

const USER = 'user@example.com';
const saved: Blob[] = [];
beforeEach(() => {
  // 화면은 재인증 만료를 실제 시계로 판단하므로 Mock 시계도 지금에서 시작합니다.
  holder.backend = null; holder.now = Date.now(); saved.length = 0;
  // jsdom 은 파일 저장을 못 하므로 저장 호출만 기록합니다(내용은 Blob 으로 검사).
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => { saved.push(blob as Blob); return 'blob:mock'; });
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
});

async function open(path: string, as?: string, personalDataUi = true) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: false, personalDataUi }),
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
const backend = () => holder.backend!;
const requestButton = () => screen.getByRole('button', { name: '내 데이터 내보내기 요청' });
async function reauth(password = MOCK_PASSWORD) {
  const dialog = await screen.findByRole('dialog', { name: '비밀번호 다시 확인' });
  const input = within(dialog).getByLabelText('비밀번호');
  expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: password } });
  fireEvent.click(within(dialog).getByRole('button', { name: '확인' }));
  return dialog;
}
async function refresh() {
  fireEvent.click(screen.getByRole('button', { name: '상태 새로 고침' }));
  await screen.findByRole('heading', { name: '요청 이력' });
}

describe('feature flag and access', () => {
  it('flag off: no menu and the URL is not found', async () => {
    await open('/me/data', USER, false);
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '내 데이터 내려받기 (Mock)' })).not.toBeInTheDocument();
  });

  it('default routes keep it off, the flag needs mock mode, and no HTTP adapter is wired', async () => {
    const { routes } = await import('../routes');
    expect(JSON.stringify(routes, (k, v) => (k === 'element' ? undefined : v))).not.toContain('me/data');
    expect(readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8'))
      .toContain("personalDataUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_PERSONAL_DATA_UI === 'true'");
    expect(readFileSync(resolve(cwd(), 'src/personal/PersonalDataServiceProvider.tsx'), 'utf8')).not.toMatch(/^import .*(createHttp|useApi)|fetch\(/m);
  });

  it('needs login and shows a menu entry when on', async () => {
    await open('/me/data');
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
    cleanup();
    await open('/me/data', USER);
    expect(await screen.findByRole('heading', { level: 1, name: '내 데이터 내려받기' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '내 데이터 내려받기 (Mock)' })).toHaveAttribute('href', '/me/data');
    expect(await screen.findByText('아직 요청한 내역이 없습니다')).toBeInTheDocument();
    expect(screen.getByText('비밀번호(암호화 값 포함)')).toBeInTheDocument();
  });
});

describe('request, re-authentication and download', () => {
  it('asks for the password first, then requests; a wrong password is announced and keeps the dialog', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    const dialog = await reauth('wrong-password');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('비밀번호가 올바르지 않습니다');
    expect(within(dialog).getByLabelText('비밀번호')).toHaveAttribute('aria-invalid', 'true');
    await reauth();
    expect(await screen.findByText(/내보내기를 요청했습니다/)).toHaveAttribute('role', 'status');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('처리 대기')).toBeInTheDocument();
    expect(requestButton()).toBeDisabled();
    expect(screen.getByText('진행 중인 내보내기 요청이 있어 새로 요청할 수 없습니다.')).toBeInTheDocument();
  });

  it('downloads once within the re-auth window, then the request is expired', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    act(() => backend().process());
    await refresh();
    expect(await screen.findByText('완료 · 내려받기 가능')).toBeInTheDocument();
    expect(screen.getByText('내려받기 기한')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /요청 파일 내려받기/ }));     // 재인증 10분 안 → 창 없이 진행
    expect(await screen.findByText(/내려받았습니다/)).toHaveAttribute('role', 'status');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('만료됨')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /요청 파일 내려받기/ })).not.toBeInTheDocument();
    expect(requestButton()).toBeEnabled();
    expect(saved).toHaveLength(1);
    const text = await saved[0]!.text();
    expect(JSON.parse(text).data.career.skills[0].name).toBe('Python');
    for (const secret of ['password_hash', 'refresh_token_hash', 'token_hash', 'client_ip_hash', 'storage_key']) expect(text).not.toContain(secret);
  });

  it('tells the user when the browser could not save the one-time file', async () => {
    vi.mocked(URL.createObjectURL).mockImplementation(() => { throw new TypeError('no blob support'); });
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    act(() => backend().process());
    await refresh();
    fireEvent.click(await screen.findByRole('button', { name: /요청 파일 내려받기/ }));
    expect(await screen.findByText(/파일을 저장하지 못했습니다/)).toHaveAttribute('role', 'alert');
  });

  it('re-auth older than 10 minutes asks again before downloading', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    act(() => backend().process());
    holder.now += 11 * 60_000;                                       // 서버(Mock) 시계가 10분 넘게 지남
    await refresh();
    fireEvent.click(await screen.findByRole('button', { name: /요청 파일 내려받기/ }));
    await reauth();
    expect(await screen.findByText(/내려받았습니다/)).toHaveAttribute('role', 'status');
  });

  it('a completed file expires after 24 hours', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    act(() => backend().process());
    holder.now += 25 * 3_600_000;
    await refresh();
    expect(await screen.findByText('만료됨')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /요청 파일 내려받기/ })).not.toBeInTheDocument();
  });

  it('cancels a waiting request after confirmation', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    fireEvent.click(await screen.findByRole('button', { name: /요청 취소$/ }));
    const dialog = await screen.findByRole('dialog', { name: '내보내기 요청을 취소할까요?' });
    fireEvent.click(within(dialog).getByRole('button', { name: '요청 취소' }));
    expect(await screen.findByText('취소됨')).toBeInTheDocument();
    expect(requestButton()).toBeEnabled();
  });
});

describe('failure, retry and errors', () => {
  it('shows a failed request with its reason and recovers after the server retries', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    act(() => { backend().failNext('process'); backend().process(); });
    await refresh();
    expect(await screen.findByText('처리 실패')).toBeInTheDocument();
    expect(screen.getByText(/자동으로 다시 시도합니다\(최대 3회\)/)).toBeInTheDocument();
    act(() => { backend().retryFailed(); backend().process(); });
    await refresh();
    expect(await screen.findByText('완료 · 내려받기 가능')).toBeInTheDocument();
  });

  it('a load error offers retry and a network error during a request is announced', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    act(() => backend().failNext('load'));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '상태 새로 고침' })); });
    expect(await screen.findByText('요청 이력을 불러오지 못했습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    act(() => { backend().process(); backend().failNext('mutate'); });
    await refresh();
    fireEvent.click(await screen.findByRole('button', { name: /요청 파일 내려받기/ }));
    expect(await screen.findByText(/서버에 연결하지 못했습니다/)).toHaveAttribute('role', 'alert');
    expect(screen.getByText('완료 · 내려받기 가능')).toBeInTheDocument();      // 실패해도 그대로, 다시 시도 가능
    fireEvent.click(screen.getByRole('button', { name: /요청 파일 내려받기/ }));
    expect(await screen.findByText(/내려받았습니다/)).toHaveAttribute('role', 'status');
  });

  it('lists the T31 deletion request with a pointer to the privacy screen', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    act(() => backend().addDeletion(USER, 'received'));
    await refresh();
    expect(await screen.findByText('회원 탈퇴(삭제)')).toBeInTheDocument();
    expect(screen.getByText('회원 탈퇴 요청은 계정 설정의 개인정보 화면에서 관리합니다.')).toBeInTheDocument();
  });
});

describe('isolation and dialog keyboard', () => {
  it('another user sees none of my requests', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    fireEvent.click(requestButton());
    await reauth();
    await screen.findByText('처리 대기');
    const mine = (await backend().serviceFor(USER).list())[0]!;
    cleanup();
    await open('/me/data', 'admin@example.com');
    expect(await screen.findByText('아직 요청한 내역이 없습니다')).toBeInTheDocument();
    await expect(backend().serviceFor('admin@example.com').cancelExport(mine.request_id)).rejects.toMatchObject({ status: 404 });
  });

  it('Esc closes the password dialog and returns focus to the button', async () => {
    await open('/me/data', USER);
    await screen.findByText('아직 요청한 내역이 없습니다');
    requestButton().focus();
    fireEvent.click(requestButton());
    const dialog = await screen.findByRole('dialog', { name: '비밀번호 다시 확인' });
    fireEvent.keyDown(dialog, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(requestButton()).toHaveFocus();
  });
});
