import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet } from '../api/client';
import { AuthContext } from '../auth/useAuth';
import type { AuthContextValue, AuthState } from '../auth/useAuth';
import { JobExplorerPage } from './JobExplorerPage';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  apiGet: vi.fn<typeof apiGet>(),
}));
const get = vi.mocked(apiGet);
const request = vi.fn<(path: string) => Promise<unknown>>();

const ANON: AuthState = { status: 'anonymous' };
const MEMBER: AuthState = { status: 'authenticated', token: 't', user: { email: 'a@example.com', displayName: '테스터', roles: [] } };

function renderPage(state: AuthState = ANON, url = '/job-roles') {
  const value: AuthContextValue = { state, login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), request: request as unknown as AuthContextValue['request'] };
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthContext.Provider value={value}><JobExplorerPage /></AuthContext.Provider>
    </MemoryRouter>,
  );
}
const role = (id: string, name: string) => ({ job_role_id: id, code: `CODE_${id}`, name });
const page = (items: ReturnType<typeof role>[], next: string | null = null) => ({ items, next_cursor: next });
const detail = (id: string, name: string, skills: [string, string, number][] = []) => ({
  ...role(id, name), description: null,
  required_skills: skills.map(([skill_id, skillName, required_level]) => ({ skill: { skill_id, name: skillName }, required_level })),
});

beforeEach(() => { get.mockReset(); request.mockReset(); });

describe('job role explorer (T17 API)', () => {
  it('shows role cards and loads the selected role detail from its own endpoint', async () => {
    get.mockResolvedValueOnce(page([role('1', '개발자')]));
    get.mockResolvedValueOnce(detail('1', '개발자', [['s1', 'Python', 3]]));
    renderPage();
    expect(await screen.findByText('CODE_1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '개발자 상세 보기' }));
    expect(await screen.findByText('Python')).toBeInTheDocument();
    expect(screen.getByText('요구 3 / 5 · 실무 가능')).toBeInTheDocument();
    expect(get).toHaveBeenLastCalledWith('/v1/job-roles/1');
    expect(screen.getByText('카탈로그에 등록된 직무 설명이 없습니다.')).toBeInTheDocument();
  });

  it('moves between pages with the returned cursor and restarts on a new search', async () => {
    get.mockResolvedValueOnce(page([role('1', '첫째')], 'next'));
    get.mockResolvedValueOnce(page([role('2', '둘째')]));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-roles?limit=20&cursor=next'));
    expect(await screen.findByText('2 페이지')).toBeInTheDocument();

    get.mockResolvedValueOnce(page([role('3', '개발')]));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: ' 개발 ' } });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-roles?limit=20&q=%EA%B0%9C%EB%B0%9C'));
    expect(await screen.findByText('1 페이지', { selector: 'span[aria-live]' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '이전' })).toBeDisabled();
  });

  it('reads the search term from the URL and clears it from the empty state', async () => {
    get.mockResolvedValueOnce(page([]));
    renderPage(ANON, '/job-roles?q=없는직무');
    expect(get).toHaveBeenCalledWith('/v1/job-roles?limit=20&q=%EC%97%86%EB%8A%94%EC%A7%81%EB%AC%B4');
    get.mockResolvedValueOnce(page([role('1', '개발자')]));
    fireEvent.click(await screen.findByRole('button', { name: '검색 조건 초기화' }));
    expect(await screen.findByText('개발자')).toBeInTheDocument();
    expect(get).toHaveBeenLastCalledWith('/v1/job-roles?limit=20');
  });

  it('shows a list error and recovers on retry', async () => {
    get.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(page([role('1', '개발자')]));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('개발자')).toBeInTheDocument();
  });

  it('ignores a slow detail response for a role that is no longer selected', async () => {
    get.mockResolvedValueOnce(page([role('1', '가'), role('2', '나')]));
    let resolveFirst: (value: ReturnType<typeof detail>) => void = () => undefined;
    get.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve as typeof resolveFirst; }));
    get.mockResolvedValueOnce(detail('2', '나', [['s2', 'SQL', 2]]));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '가 상세 보기' }));
    fireEvent.click(screen.getByRole('button', { name: '나 상세 보기' }));
    expect(await screen.findByText('SQL')).toBeInTheDocument();
    resolveFirst(detail('1', '가', [['s1', 'LATE-ONLY', 5]]));
    await Promise.resolve();
    expect(screen.queryByText('LATE-ONLY')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '나' })).toBeInTheDocument();
  });
});

describe('my skills comparison (T33 /me/skills)', () => {
  it('asks anonymous visitors to log in and never calls /me/skills', async () => {
    get.mockResolvedValueOnce(page([role('1', '개발자')]));
    get.mockResolvedValueOnce(detail('1', '개발자', [['s1', 'Python', 3]]));
    renderPage(ANON);
    fireEvent.click(await screen.findByRole('button', { name: '개발자 상세 보기' }));
    expect(await screen.findByRole('link', { name: '로그인' })).toHaveAttribute('href', '/login');
    expect(request).not.toHaveBeenCalled();
  });

  it('compares required levels with the signed-in user skills without faking a score', async () => {
    get.mockResolvedValueOnce(page([role('1', '개발자')]));
    get.mockResolvedValueOnce(detail('1', '개발자', [['a', 'Python', 3], ['b', 'SQL', 4], ['c', 'Git', 2], ['d', 'Docker', 1]]));
    request.mockResolvedValueOnce([
      { skill: { skill_id: 'a', name: 'Python' }, proficiency: 3 },
      { skill: { skill_id: 'b', name: 'SQL' }, proficiency: 2 },
      { skill: { skill_id: 'c', name: 'Git' }, proficiency: null },
    ]);
    renderPage(MEMBER);
    fireEvent.click(await screen.findByRole('button', { name: '개발자 상세 보기' }));
    expect(await screen.findByText('요구 기술 4개 중 1개 충족')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/v1/me/skills');
    const rows = screen.getByRole('list', { name: '내 보유 기술 비교 결과' });
    expect(within(rows).getByText('충족')).toBeInTheDocument();
    expect(within(rows).getByText('부족 (2단계)')).toBeInTheDocument();
    expect(within(rows).getByText('숙련도 미입력')).toBeInTheDocument();
    expect(within(rows).getByText('보유 기술에 없음')).toBeInTheDocument();
  });

  it('keeps the role detail visible when my skills fail and lets the user retry', async () => {
    get.mockResolvedValueOnce(page([role('1', '개발자')]));
    get.mockResolvedValueOnce(detail('1', '개발자', [['a', 'Python', 3]]));
    request.mockRejectedValueOnce(new ApiError(500, '/v1/me/skills')).mockResolvedValueOnce([]);
    renderPage(MEMBER);
    fireEvent.click(await screen.findByRole('button', { name: '개발자 상세 보기' }));
    expect(await screen.findByText('Python')).toBeInTheDocument();
    const retry = await screen.findByRole('button', { name: '다시 시도' });
    fireEvent.click(retry);
    expect(await screen.findByText('요구 기술 1개 중 0개 충족')).toBeInTheDocument();
    expect(screen.getByText('보유 기술에 없음')).toBeInTheDocument();
    expect(screen.getByText(/아직 등록한 보유 기술이 없습니다/)).toBeInTheDocument();
  });
});
