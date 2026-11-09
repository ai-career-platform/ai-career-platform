import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import type { Match } from '../api/matches';
import { RequireAuth } from '../auth/RequireAuth';
import { AuthContext } from '../auth/useAuth';
import type { AuthContextValue } from '../auth/useAuth';
import { fixtureMatch, resetMatchMocks } from '../mocks/matches';
import { resetSkillsMocks } from '../mocks/skills';
import { mockHttp, type RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { MatchResultPage } from './MatchResultPage';

const MATCH = '11111111-1111-4111-8111-111111111111';
const POSTING = '22222222-2222-4222-8222-222222222222';
const ROLE = '33333333-3333-4333-8333-333333333333';
const skill = (skill_id: string, name: string) => ({ skill_id, code: name.toUpperCase(), name });

/** 고정 fixture: 계약 예시와 같은 점수(62.5) + 공고 요구 기술 4개 + 내 보유 기술 3개. */
const postingDetail = {
  job_posting_id: POSTING, title: '백엔드 개발자', status: 'published', company: { company_id: 'c', name: '알파' },
  job_role: { job_role_id: ROLE, name: '백엔드' }, employment_type: null, location_text: null, published_at: null, expires_at: null,
  description: null, source_url: null, is_bookmarked: null,
  required_skills: [
    { skill: skill('s1', 'Python'), required_level: 3, is_required: true },
    { skill: skill('s2', 'SQL'), required_level: 4, is_required: true },
    { skill: skill('s3', 'Docker'), required_level: 2, is_required: false },
    { skill: skill('s4', 'Git'), required_level: null, is_required: false },
  ],
};
const roleDetail = {
  job_role_id: ROLE, code: 'BACKEND', name: '백엔드 엔지니어', description: null,
  required_skills: [{ skill: skill('s1', 'Python'), required_level: 4 }],
};
const mySkills = [
  { skill: skill('s1', 'Python'), proficiency: 4 },
  { skill: skill('s2', 'SQL'), proficiency: 2 },
  { skill: skill('s4', 'Git'), proficiency: null },
];

const settle = (value: unknown) => (value instanceof Error ? Promise.reject(value) : Promise.resolve(value));

function show({ match = fixtureMatch(MATCH, { job_posting_id: POSTING, job_role_id: null }) as Match | Error,
  skills = mySkills as unknown, url = `/matches/${MATCH}`, anonymous = false, extra }: {
  match?: Match | Error; skills?: unknown; url?: string; anonymous?: boolean; extra?: RequestFn;
} = {}) {
  const request = vi.fn<RequestFn>((path, init) => {
    const handled = extra?.(path, init);
    if (handled) return handled;
    if (path === `/v1/matches/${MATCH}`) return settle(match);
    if (path === '/v1/me/skills') return settle(skills);
    if (path.startsWith('/v1/job-postings/')) return settle(postingDetail);
    if (path.startsWith('/v1/job-roles/')) return settle(roleDetail);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  const auth: AuthContextValue = {
    state: anonymous ? { status: 'anonymous' } : { status: 'authenticated', token: 't', user: { email: 'a@example.com', displayName: '테스터', roles: [] } },
    login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(),
  };
  const view = render(
    <AuthContext.Provider value={auth}>
      <WithApi request={request}>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route element={<RequireAuth />}><Route path="/matches/:matchId" element={<MatchResultPage />} /></Route>
            <Route path="/login" element={<h1>로그인 필요</h1>} />
          </Routes>
        </MemoryRouter>
      </WithApi>
    </AuthContext.Provider>,
  );
  return { request, view };
}

const calls = (request: ReturnType<typeof show>['request'], path: string) => request.mock.calls.filter(([p]) => p === path);
const evidenceRows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1)
  .map((row) => [...row.querySelectorAll('th, td')].map((cell) => cell.textContent));

beforeEach(() => { resetMatchMocks(); resetSkillsMocks(); });

describe('T42 적합도 결과 화면 (UI-015)', () => {
  it('점수·충족/부족 수·한계 설명·계산 기준·분석 시점을 서버 결과 그대로 보여 준다', async () => {
    const { view } = show();
    expect(await screen.findByRole('heading', { name: '백엔드 개발자' })).toBeInTheDocument();
    expect(screen.getByText('알파 · 백엔드')).toBeInTheDocument();
    expect(screen.getByLabelText('적합도 62.5점 (100점 만점)')).toBeInTheDocument();
    expect(screen.getByText('충족한 요구 기술').nextSibling).toHaveTextContent('5개');
    expect(screen.getByText('부족한 요구 기술').nextSibling).toHaveTextContent('3개');
    expect(screen.getByText('자기평가 숙련도 기준이며 채용 결과를 예측하지 않습니다.')).toBeInTheDocument();
    expect(screen.getByText('match_rule v1 (규칙 기반)')).toBeInTheDocument();
    // 2026-11-06T03:00:00Z → 한국 시각 12:00
    expect(screen.getByText('분석 시점').nextSibling).toHaveTextContent('2026년 11월 6일 12:00');
    expect(screen.getByText(/합격 확률이나 다른 지원자와의 비교 순위가 아닙니다/)).toBeInTheDocument();
    // 미확정 점수 해석 금지: 백분율·백분위·합격 가능성 표현 없음
    expect(view.container.textContent).not.toMatch(/%|백분위|상위\s*\d|합격 가능/);
  });

  it('근거 표: 필수 먼저, 부족·미입력 등 확인이 필요한 기술을 위로 올린다 (고정 fixture 재현)', async () => {
    show();
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(evidenceRows()).toEqual([
      ['SQL', '필수', '4 · 능숙', '2 · 기초', '부족 (2단계)'],
      ['Python', '필수', '3 · 실무 가능', '4 · 능숙', '충족'],
      ['Docker', '우대', '2 · 기초', '—', '보유 기술에 없음'],
      ['Git', '우대', '미등록', '—', '숙련도 미입력'],
    ]);
    expect(screen.getByText(/계산 뒤에 보유 기술을 바꿨다면 위 점수와 다를 수 있어요/)).toBeInTheDocument();
  });

  it('직무 결과는 직무 상세(T17)의 요구 기술을 쓰고 모두 필수로 표시한다', async () => {
    const { request } = show({ match: fixtureMatch(MATCH, { job_posting_id: null, job_role_id: ROLE }) });
    expect(await screen.findByRole('heading', { name: '백엔드 엔지니어' })).toBeInTheDocument();
    expect(calls(request, `/v1/job-roles/${ROLE}`)).toHaveLength(1);
    expect(evidenceRows()).toEqual([['Python', '필수', '4 · 능숙', '4 · 능숙', '충족']]);
    expect(screen.getByRole('link', { name: '직무 목록으로' })).toHaveAttribute('href', '/job-roles');
  });

  it('계산 실패(failed)면 점수 없이 이유(한계 설명)를 보여 준다', async () => {
    show({ match: { ...fixtureMatch(MATCH, { job_posting_id: POSTING, job_role_id: null }), status: 'failed', score: null,
      matched_skill_count: null, missing_skill_count: null,
      limitations: ['자기평가 숙련도 기준이며 채용 결과를 예측하지 않습니다.', '요구 기술 정보가 없어 적합도를 계산할 수 없습니다.'] } });
    expect(await screen.findByText('점수를 계산하지 못했습니다')).toBeInTheDocument();
    expect(screen.queryByLabelText(/100점 만점/)).not.toBeInTheDocument();
    expect(screen.getByText('요구 기술 정보가 없어 적합도를 계산할 수 없습니다.')).toBeInTheDocument();
  });

  it('마감 공고 결과의 안내 문구도 그대로 보여 준다', async () => {
    show({ match: { ...fixtureMatch(MATCH, { job_posting_id: POSTING, job_role_id: null }),
      limitations: ['자기평가 숙련도 기준이며 채용 결과를 예측하지 않습니다.', '숙련도를 입력하지 않은 기술은 0으로 계산했습니다.', '마감된 공고입니다.'] } });
    expect(await screen.findByText('마감된 공고입니다.')).toBeInTheDocument();
    expect(screen.getByText('숙련도를 입력하지 않은 기술은 0으로 계산했습니다.')).toBeInTheDocument();
  });

  it('남의 결과·없는 결과(404)는 "찾을 수 없음"으로, 잘못된 주소는 API를 부르지 않는다', async () => {
    show({ match: new ApiError(404, `/v1/matches/${MATCH}`, undefined, 'NOT_FOUND') });
    expect(await screen.findByText('적합도 결과를 찾을 수 없습니다')).toBeInTheDocument();

    const { request } = show({ url: '/matches/not-a-uuid' });
    expect(screen.getAllByText('적합도 결과를 찾을 수 없습니다').length).toBeGreaterThan(0);
    expect(request).not.toHaveBeenCalled();
  });

  it('불러오기 실패는 다시 시도할 수 있다', async () => {
    const { request } = show({ match: new ApiError(500, `/v1/matches/${MATCH}`) });
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(calls(request, `/v1/matches/${MATCH}`)).toHaveLength(2);
  });

  it('보유 기술을 못 불러와도 점수는 보이고 근거만 다시 시도할 수 있다', async () => {
    show({ skills: new ApiError(500, '/v1/me/skills') });
    expect(await screen.findByText('내 보유 기술을 불러오지 못했습니다')).toBeInTheDocument();
    expect(screen.getByLabelText('적합도 62.5점 (100점 만점)')).toBeInTheDocument();
  });

  it('다시 계산하면 같은 대상으로 POST 하고 새 결과로 이동한다', async () => {
    const NEXT = '44444444-4444-4444-8444-444444444444';
    const next = { ...fixtureMatch(NEXT, { job_posting_id: POSTING, job_role_id: null }), score: 75 };
    const { request } = show({ extra: (path, init) => {
      if (path === '/v1/matches' && init?.method === 'POST') return Promise.resolve(next);
      if (path === `/v1/matches/${NEXT}`) return Promise.resolve(next);
      return undefined as unknown as Promise<unknown>;
    } });
    fireEvent.click(await screen.findByRole('button', { name: '지금 보유 기술로 다시 계산' }));
    expect(await screen.findByLabelText('적합도 75점 (100점 만점)')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/v1/matches', expect.objectContaining({ method: 'POST', body: { job_posting_id: POSTING } }));
  });

  it('다시 계산할 때 보유 기술이 없으면(400) 보유 기술 화면으로 안내한다', async () => {
    show({ extra: (path, init) => path === '/v1/matches' && init?.method === 'POST'
      ? Promise.reject(new ApiError(400, '/v1/matches', undefined, 'NO_USER_SKILLS'))
      : undefined as unknown as Promise<unknown> });
    fireEvent.click(await screen.findByRole('button', { name: '지금 보유 기술로 다시 계산' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('등록된 보유 기술이 없어 적합도를 계산할 수 없습니다.');
    expect(screen.getByRole('link', { name: '보유 기술 등록하기' })).toHaveAttribute('href', '/me/skills');
  });

  it('비로그인이면 RequireAuth로 로그인 화면에 보내고 API를 부르지 않는다', async () => {
    const { request } = show({ anonymous: true });
    expect(await screen.findByRole('heading', { name: '로그인 필요' })).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
});

describe('T42 Mock 적합도 API (VITE_API_MOCK — 실제 서비스 PASS 아님)', () => {
  const as = (email: string) => mockHttp(`mock-access-${email}`);

  it('보유 기술이 없으면 400, 등록 후 201 고정 결과, 다른 사용자는 404', async () => {
    const user = as('user@example.com');
    await expect(user.request('/v1/matches', { method: 'POST', body: { job_posting_id: POSTING } }))
      .rejects.toMatchObject({ status: 400, code: 'NO_USER_SKILLS' });
    await user.request('/v1/me/skills', { method: 'PUT', body: { items: [{ skill_id: '00000000-0000-4000-8000-000000000001', proficiency: 3 }] } });
    const created = await user.request<Match>('/v1/matches', { method: 'POST', body: { job_posting_id: POSTING } });
    expect(created).toMatchObject({ status: 'completed', score: 62.5, score_is_probability: false, target: { job_posting_id: POSTING, job_role_id: null } });
    expect(await user.request<Match>(`/v1/matches/${created.match_id}`)).toEqual(created);
    await expect(as('admin@example.com').request(`/v1/matches/${created.match_id}`)).rejects.toMatchObject({ status: 404 });
  });

  it('대상 둘 다·없음·잘못된 ID는 422', async () => {
    const user = as('user@example.com');
    for (const body of [{}, { job_posting_id: POSTING, job_role_id: ROLE }, { job_role_id: 'x' }]) {
      await expect(user.request('/v1/matches', { method: 'POST', body })).rejects.toMatchObject({ status: 422 });
    }
  });
});
