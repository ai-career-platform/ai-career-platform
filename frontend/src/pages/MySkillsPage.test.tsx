import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import { RequireAuth } from '../auth/RequireAuth';
import { ApiError, apiRequest, type ApiRequestOptions } from '../api/client';
import { resetSkillsMocks } from '../mocks/skills';
import { MySkillsPage } from './MySkillsPage';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

type RequestFn = (path: string, options?: ApiRequestOptions) => Promise<unknown>;
const viaMock: RequestFn = (path, options = {}) =>
  apiRequest(path, { ...options, token: 'mock-access-user@example.com', mockEnabled: true });

function show({ anonymous = false, custom }: { anonymous?: boolean; custom?: RequestFn } = {}) {
  const request = vi.fn<RequestFn>(custom ?? viaMock);
  const value: AuthContextValue = {
    state: anonymous ? { status: 'anonymous' } : { status: 'authenticated', token: 'mock-access-user@example.com',
      user: { email: 'user@example.com', displayName: '합성 사용자', roles: ['job_seeker'] } },
    login: vi.fn<AuthContextValue['login']>().mockResolvedValue(undefined),
    logout: vi.fn<AuthContextValue['logout']>().mockResolvedValue(undefined),
    request: <T,>(path: string, options?: ApiRequestOptions) => request(path, options) as Promise<T>,
  };
  const view = render(<AuthContext.Provider value={value}><MemoryRouter initialEntries={['/me/skills']}>
    <Routes><Route element={<Outlet />}><Route element={<RequireAuth />}>
      <Route path="/me/skills" element={<MySkillsPage />} />
    </Route><Route path="/login" element={<h1>로그인 필요</h1>} /></Route></Routes>
  </MemoryRouter></AuthContext.Provider>);
  return { request, view };
}

const loaded = () => screen.findByRole('combobox', { name: '기술 검색' });
const rows = () => screen.queryAllByRole('listitem').filter(li => li.classList.contains('skills-row'));
const rowNames = () => rows().map(li => li.querySelector('.skills-name')!.firstChild!.textContent);
const puts = (request: ReturnType<typeof show>['request']) =>
  request.mock.calls.filter(([path, o]) => path === '/v1/me/skills' && o?.method === 'PUT');

async function searchAndPick(text: string, optionName: RegExp) {
  const box = await loaded();
  fireEvent.change(box, { target: { value: text } });
  fireEvent.click(await screen.findByRole('option', { name: optionName }));
}

beforeEach(() => resetSkillsMocks());

describe('T34 나의 기술 (Mock — 실제 PostgreSQL 증빙 아님)', () => {
  it('비로그인이면 기존 RequireAuth로 로그인 화면에 보내고 API를 부르지 않는다', async () => {
    const { request } = show({ anonymous: true });
    expect(await screen.findByRole('heading', { name: '로그인 필요' })).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });

  it('처음에는 빈 상태 안내와 자기평가 안내를 보여준다', async () => {
    show();
    expect(screen.getByText('내 기술을 불러오는 중')).toBeInTheDocument();
    await loaded();
    expect(screen.getByText('기술을 1개 이상 등록하면 분석을 받을 수 있습니다.')).toBeInTheDocument();
    expect(screen.getByText('자기평가')).toBeInTheDocument();
    expect(screen.getByText(/실제 PostgreSQL 저장이 아닙니다/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled();
  });

  it('추가·숙련도 수정·삭제 후 저장하면 다시 조회한 결과와 일치한다', async () => {
    const first = show();
    await searchAndPick('py', /^Python/);
    await searchAndPick('sql', /^PostgreSQL/);
    fireEvent.change(screen.getByLabelText('Python 숙련도'), { target: { value: '3' } });
    expect(screen.getByText('저장하지 않은 변경이 있습니다.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await screen.findByText('저장했습니다.');
    expect(puts(first.request)[0]![1]!.body).toEqual({ items: [
      { skill_id: expect.any(String), proficiency: 3 }, { skill_id: expect.any(String), proficiency: null },
    ] });
    expect(rowNames()).toEqual(['PostgreSQL', 'Python']); // 서버 응답(이름순)으로 갱신

    fireEvent.change(screen.getByLabelText('Python 숙련도'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'PostgreSQL 삭제' }));
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await screen.findByText('저장했습니다.');
    first.view.unmount();

    show(); // 새로 열어서 다시 조회
    await loaded();
    expect(rowNames()).toEqual(['Python']);
    expect(screen.getByLabelText('Python 숙련도')).toHaveValue('5');
  });

  it('키보드만으로 검색 결과를 고르고 Escape로 닫을 수 있다', async () => {
    show();
    const box = await loaded();
    fireEvent.change(box, { target: { value: 'py' } });
    await screen.findAllByRole('option');
    expect(box).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    const active = box.getAttribute('aria-activedescendant')!;
    const name = document.getElementById(active)!.textContent!.trim();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(rowNames()).toEqual([name]);
    expect(box).toHaveFocus();
    fireEvent.change(box, { target: { value: 'ja' } });
    await screen.findAllByRole('option');
    fireEvent.keyDown(box, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('같은 기술은 두 번 추가되지 않는다', async () => {
    show();
    await searchAndPick('py', /^Python/);
    fireEvent.change(screen.getByRole('combobox', { name: '기술 검색' }), { target: { value: 'pyth' } });
    const option = await screen.findByRole('option', { name: /^Python/ });
    expect(option).toHaveAttribute('aria-disabled', 'true');
    expect(within(option).getByText('추가됨')).toBeInTheDocument();
    fireEvent.click(option);
    expect(screen.getByText('Python은(는) 이미 추가한 기술입니다.')).toBeInTheDocument();
    expect(rowNames()).toEqual(['Python']);
  });

  it('목록에 없는 기술은 직접 입력해도 추가되지 않는다', async () => {
    const { request } = show();
    const box = await loaded();
    fireEvent.change(box, { target: { value: '없는기술' } });
    expect(await screen.findByText('검색 결과가 없습니다. 다른 이름으로 찾아보세요.')).toBeInTheDocument();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByText(/목록에 있는 기술만 추가할 수 있습니다/)).toBeInTheDocument();
    expect(rows()).toHaveLength(0);
    expect(puts(request)).toHaveLength(0);
  });

  it('1글자로는 검색하지 않는다', async () => {
    const { request } = show();
    const box = await loaded();
    fireEvent.change(box, { target: { value: 'p' } });
    await new Promise(r => setTimeout(r, 400));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(request.mock.calls.some(([path]) => path.startsWith('/v1/skills'))).toBe(false);
  });

  it('저장에 실패하면 서버 문구를 보여주고 수정 내용을 유지하며, 저장된 상태로 되돌릴 수 있다', async () => {
    const failing: RequestFn = (path, options = {}) => options.method === 'PUT'
      ? Promise.reject(new ApiError(503, path, undefined, 'DEPENDENCY_UNAVAILABLE', '서비스를 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'))
      : viaMock(path, options);
    show({ custom: failing });
    await searchAndPick('py', /^Python/);
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('서비스를 잠시 사용할 수 없습니다.');
    expect(alert).toHaveTextContent('화면의 수정 내용은 그대로 남아 있습니다.');
    expect(rowNames()).toEqual(['Python']);
    expect(screen.getByRole('button', { name: '저장' })).toBeEnabled(); // 다시 시도 가능

    fireEvent.click(screen.getByRole('button', { name: '저장된 상태로 되돌리기' }));
    expect(rows()).toHaveLength(0);
    expect(screen.getByText('저장된 상태로 되돌렸습니다.')).toBeInTheDocument();
  });

  it('저장 중에는 버튼을 막아 중복 요청을 보내지 않는다', async () => {
    const { request } = show();
    await searchAndPick('py', /^Python/);
    const save = screen.getByRole('button', { name: '저장' });
    fireEvent.click(save); fireEvent.click(save);
    expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled();
    await screen.findByText('저장했습니다.');
    expect(puts(request)).toHaveLength(1);
  });

  it('불러오기에 실패하면 다시 시도할 수 있다', async () => {
    let fail = true;
    show({ custom: (path, options) => fail && path === '/v1/me/skills'
      ? Promise.reject(new ApiError(0, path)) : viaMock(path, options) });
    expect(await screen.findByText('서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.')).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await loaded();
  });

  it('[리뷰 회귀] 늦게 도착한 이전 검색 응답이 최신 결과를 덮어쓰지 않는다', async () => {
    const pending = new Map<string, (v: unknown) => void>();
    show({ custom: (path, options) => {
      if (!path.startsWith('/v1/skills')) return viaMock(path, options);
      const q = new URLSearchParams(path.split('?')[1]).get('q')!;
      return new Promise(resolve => pending.set(q, resolve));
    } });
    const box = await loaded();
    fireEvent.change(box, { target: { value: 'py' } });
    await waitFor(() => expect(pending.has('py')).toBe(true)); // py 요청 전송됨(응답 대기)
    fireEvent.change(box, { target: { value: 'java' } });
    await waitFor(() => expect(pending.has('java')).toBe(true));
    const skill = (name: string, i: number) => ({ skill_id: `00000000-0000-4000-8000-${String(90 + i).padStart(12, '0')}`, code: name.toUpperCase(), name });
    pending.get('java')!({ items: [skill('Java', 1), skill('JavaScript', 2)] }); // 최신 응답 먼저
    expect(await screen.findByRole('option', { name: 'Java' })).toBeInTheDocument();
    pending.get('py')!({ items: [skill('Python', 3)] }); // 이전 응답이 나중에 도착
    await new Promise(r => setTimeout(r, 50));
    expect(screen.getByRole('option', { name: 'Java' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Python' })).not.toBeInTheDocument();
    expect(screen.queryByText('검색 중…')).not.toBeInTheDocument();
  });

  it('[리뷰 회귀] 늦게 실패한 이전 검색이 최신 결과를 오류로 바꾸지 않는다', async () => {
    const pending = new Map<string, { resolve: (v: unknown) => void; reject: (e: unknown) => void }>();
    show({ custom: (path, options) => {
      if (!path.startsWith('/v1/skills')) return viaMock(path, options);
      const q = new URLSearchParams(path.split('?')[1]).get('q')!;
      return new Promise((resolve, reject) => pending.set(q, { resolve, reject }));
    } });
    const box = await loaded();
    fireEvent.change(box, { target: { value: 'py' } });
    await waitFor(() => expect(pending.has('py')).toBe(true));
    fireEvent.change(box, { target: { value: 'sql' } });
    await waitFor(() => expect(pending.has('sql')).toBe(true));
    pending.get('sql')!.resolve({ items: [{ skill_id: '00000000-0000-4000-8000-000000000099', code: 'SQL', name: 'SQL' }] });
    expect(await screen.findByRole('option', { name: 'SQL' })).toBeInTheDocument();
    pending.get('py')!.reject(new ApiError(503, '/v1/skills'));
    await new Promise(r => setTimeout(r, 50));
    expect(screen.getByRole('option', { name: 'SQL' })).toBeInTheDocument();
    expect(screen.queryByText(/검색하지 못했습니다/)).not.toBeInTheDocument();
  });

  it('[리뷰 회귀] 저장 중에는 검색 결과를 골라 추가할 수 없어 저장 후 사라지는 일이 없다', async () => {
    let finishPut: (() => void) | undefined;
    show({ custom: (path, options = {}) => options.method === 'PUT'
      ? new Promise(resolve => { finishPut = () => resolve(viaMock(path, options)); })
      : viaMock(path, options) });
    await searchAndPick('py', /^Python/);
    const box = screen.getByRole('combobox', { name: '기술 검색' });
    fireEvent.change(box, { target: { value: 'sql' } });
    const option = await screen.findByRole('option', { name: /^SQL/ });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(finishPut).toBeDefined());
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument(); // 저장 중 목록 닫힘
    fireEvent.click(option); // 닫히기 직전 요소를 클릭해도
    fireEvent.keyDown(box, { key: 'Enter' }); // 키보드로 골라도
    expect(rowNames()).toEqual(['Python']);
    finishPut!();
    await screen.findByText('저장했습니다.');
    expect(rowNames()).toEqual(['Python']);
    expect(screen.queryByText('저장하지 않은 변경이 있습니다.')).not.toBeInTheDocument();
  });

  it('Mock 서버도 Backend와 같은 규칙으로 중복·범위 밖 숙련도를 거부한다', async () => {
    const id = '00000000-0000-4000-8000-000000000001';
    const call = (body: unknown) => viaMock('/v1/me/skills', { method: 'PUT', body });
    await expect(call({ items: [{ skill_id: id }, { skill_id: id }] })).rejects.toMatchObject({ status: 422, code: 'DUPLICATE_SKILL' });
    await expect(call({ items: [{ skill_id: id, proficiency: 6 }] })).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(call({ items: [{ skill_id: '00000000-0000-4000-8000-000000000014' }] })).rejects.toMatchObject({ code: 'VALIDATION_FAILED' }); // 폐기 기술
  });
});

describe('API client — PUT과 오류 문구', () => {
  it('PUT 본문을 JSON으로 보내고, 오류 응답의 message를 userMessage로 전달한다', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(
      JSON.stringify({ code: 'DUPLICATE_SKILL', status: 422, message: '같은 기술이 중복으로 들어 있습니다.' }),
      { status: 422, headers: { 'Content-Type': 'application/json' } },
    ));
    const body = { items: [{ skill_id: 'a', proficiency: 2 }] };
    await expect(apiRequest('/v1/me/skills', { method: 'PUT', body, token: 't', mockEnabled: false, fetchImpl }))
      .rejects.toMatchObject({ status: 422, code: 'DUPLICATE_SKILL', userMessage: '같은 기술이 중복으로 들어 있습니다.' });
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe('/api/v1/me/skills');
    expect(init).toMatchObject({ method: 'PUT', body: JSON.stringify(body) });
    await waitFor(() => expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer t'));
  });
});
