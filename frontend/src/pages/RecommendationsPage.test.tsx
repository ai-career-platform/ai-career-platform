import { fireEvent, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { resetRecommendationMock, setRecommendationMockScenario } from '../mocks/recommendations';
import { routes } from '../routes';

// 화면 테스트는 T45 Backend 응답 모양에 맞춘 Mock(mocks/recommendations.ts)으로 처리한다. 실제 API 연결 검증은 아니다.
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

const setup = (path: string) => {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
};

async function signIn(email = 'user@example.com') {
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

/** 로그인 화면을 거쳐 /recommendations 로 돌아온 상태를 만든다. */
async function openRecommendations() {
  const router = setup('/recommendations');
  await signIn();
  await screen.findByRole('heading', { name: '맞춤 공고 추천' });
  return router;
}

const list = () => screen.findByRole('list', { name: '추천 공고 목록' });
/** 추천 카드(목록의 직계 li). 카드 안의 JobCard 도 article 이라 role 대신 직계 자식으로 셉니다. */
const cards = async () => Array.from((await list()).children) as HTMLElement[];
const at = (elements: HTMLElement[], index: number) => {
  const element = elements[index];
  if (!element) throw new Error(`card #${index} not found`);
  return element;
};

beforeEach(() => resetRecommendationMock());
afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe('RecommendationsPage (UI-017)', () => {
  it('requires login: anonymous users are redirected to login and come back after signing in', async () => {
    setup('/recommendations');
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
    await signIn();
    expect(await screen.findByRole('heading', { name: '맞춤 공고 추천' })).toBeInTheDocument();
  });

  it('shows the latest run with rank, score meaning, reason, model version and generated time', async () => {
    await openRecommendations();
    const items = await cards();
    expect(items).toHaveLength(3);

    const first = at(items, 0);
    expect(within(first).getByText(/1위 · 백엔드 개발자 \(신입\)/)).toBeInTheDocument();
    expect(within(first).getByRole('heading', { level: 2, name: '1위 · 백엔드 개발자 (신입)' })).toBeInTheDocument();
    expect(within(first).getByText('적합 점수 100점 만점에 75점')).toHaveClass('sr-only');
    expect(within(first).getByText('75').closest('[aria-hidden="true"]')).not.toBeNull();
    const info = within(first).getByRole('list', { name: '공고 정보' });
    expect(within(info).getByText('정규직')).toBeInTheDocument();
    expect(within(first).queryByRole('list', { name: '관련 기술' })).not.toBeInTheDocument();
    expect(within(first).getByText(/합격 가능성\(확률\)이 아닙니다/)).toBeInTheDocument();
    expect(within(first).getByText(/요구 기술과 얼마나 일치하는지/)).toBeInTheDocument();
    expect(within(first).getByText('요구 기술 4개 중 3개가 일치합니다. 목표 직무에 포함됩니다.')).toBeInTheDocument();
    expect(within(first).getByText('예시 테크', { selector: '.job-company' })).toBeInTheDocument();

    expect(screen.getByText('맞춤 추천', { selector: '.recommendations-badge' })).toHaveClass('recommendations-badge--completed');
    expect(screen.getByText('skill_overlap_baseline · skill-overlap-draft-v2 (규칙 기반)')).toBeInTheDocument();
    expect(screen.getByText(/AI의 확정 판단이 아니므로/)).toBeInTheDocument();
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-11-06T03:10:00Z');
  });

  it('does not link to the missing detail route; shows a pending note and links to the job postings list', async () => {
    const router = await openRecommendations();
    const scope = within(await list());
    expect(scope.queryByRole('link', { name: /공고 상세 보기/ })).not.toBeInTheDocument();
    expect(scope.getAllByText('공고 상세 화면 준비 중').length).toBeGreaterThan(0);
    const link = scope.getByRole('link', { name: '백엔드 개발자 (신입) — 채용공고 목록에서 찾기' });
    expect(link).toHaveAttribute('href', '/job-postings');

    fireEvent.click(link);
    expect(router.state.location.pathname).toBe('/job-postings');
    expect(await screen.findByRole('heading', { level: 1 })).not.toHaveTextContent('페이지를 찾을 수 없습니다');
  });

  it('shows the empty state when there is no recommendation yet (404) and creates one from the CTA', async () => {
    setRecommendationMockScenario({ latest: 'none' });
    await openRecommendations();

    expect(await screen.findByText('아직 받은 추천이 없습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '추천 받기' }));

    expect(await list()).toBeInTheDocument();
    expect(screen.getByText('맞춤 추천', { selector: '.recommendations-badge' })).toBeInTheDocument();
    expect(screen.queryByText('아직 받은 추천이 없습니다')).not.toBeInTheDocument();
  });

  it('refreshes with a new run (POST) and shows the new generated time', async () => {
    await openRecommendations();
    await list();
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-11-06T03:10:00Z');

    fireEvent.click(screen.getByRole('button', { name: '새 추천 받기' }));
    expect(await screen.findByRole('button', { name: '추천 계산 중…' })).toBeDisabled();
    expect(await screen.findByRole('button', { name: '새 추천 받기' })).toBeEnabled();
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-11-09T01:01:00.000Z');

    // 관심 없음으로 표시한 공고는 새 추천에서 빠지고, 나머지 피드백(내 최신 피드백)은 유지된다
    const items = await cards();
    expect(items).toHaveLength(2);
    expect(screen.queryByText(/데이터 엔지니어 \(주니어\)/)).not.toBeInTheDocument();
    expect(within(at(items, 1)).getByText(/2위 · Python 서버 개발자/)).toBeInTheDocument();
    expect(within(at(items, 1)).getByText('관심 있음 표시함')).toBeInTheDocument();
  });

  it('marks a fallback run as 기준 추천 (not personalized) and shows no numeric score', async () => {
    setRecommendationMockScenario({ latest: 'fallback' });
    await openRecommendations();
    const items = await cards();

    expect(screen.getByText('기준 추천 (개인화 아님)')).toHaveClass('recommendations-badge--fallback');
    expect(screen.getByRole('note')).toHaveTextContent('맞춤 추천을 계산하지 못해');
    expect(screen.getByRole('note')).not.toHaveTextContent('입력하면 맞춤 추천을 받을 수 있습니다');
    expect(screen.getByText('skill_overlap_baseline · skill-overlap-draft-v2 (규칙 기반)')).toBeInTheDocument();
    expect(within(at(items, 0)).getByText('점수 없음')).toBeInTheDocument();
    expect(within(at(items, 0)).getByText('기준 추천이라 개인 적합 점수를 계산하지 않았습니다.')).toBeInTheDocument();
    expect(screen.queryByText(/적합 점수 100점 만점에/)).not.toBeInTheDocument();
  });

  it('shows the T45 fallback reason, and an empty state when a fallback run has no published postings', async () => {
    setRecommendationMockScenario({ latest: 'fallback' });
    await openRecommendations();
    const items = await cards();
    expect(within(at(items, 0)).getByText('보유 기술 또는 공고의 요구 기술 정보가 부족하여 최신 공고를 표시합니다.')).toBeInTheDocument();

    setRecommendationMockScenario({ create: 'fallback_empty' });
    fireEvent.click(screen.getByRole('button', { name: '새 추천 받기' }));
    expect(await screen.findByText('추천할 공고가 없습니다')).toBeInTheDocument();
    expect(screen.getByText('기준 추천 (개인화 아님)')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: '추천 공고 목록' })).not.toBeInTheDocument();
  });

  it('shows a failed run clearly with a retry action', async () => {
    setRecommendationMockScenario({ latest: 'none', create: 'failed' });
    await openRecommendations();
    fireEvent.click(await screen.findByRole('button', { name: '추천 받기' }));

    expect(await screen.findByText('추천 계산에 실패했습니다')).toBeInTheDocument();
    expect(screen.getByText('추천 실패')).toHaveClass('recommendations-badge--failed');

    setRecommendationMockScenario({ create: 'completed' });
    fireEvent.click(screen.getByRole('button', { name: '다시 추천 받기' }));
    expect(await list()).toBeInTheDocument();
  });

  it('shows an error state when loading fails and recovers on retry', async () => {
    setRecommendationMockScenario({ latest: 'error' });
    await openRecommendations();
    expect(await screen.findByRole('alert')).toHaveTextContent('추천을 불러오지 못했습니다');

    setRecommendationMockScenario({ latest: 'personalized' });
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await list()).toBeInTheDocument();
  });

  it('keeps the current list and shows an alert when a refresh fails', async () => {
    setRecommendationMockScenario({ create: 'error' });
    await openRecommendations();
    await list();

    fireEvent.click(screen.getByRole('button', { name: '새 추천 받기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('새 추천을 받지 못했습니다');
    expect(await cards()).toHaveLength(3);
  });

  it('filters cards by my feedback state on the client', async () => {
    await openRecommendations();
    await list();
    const filters = within(screen.getByRole('group', { name: '피드백 상태로 거르기' }));

    fireEvent.click(filters.getByRole('button', { name: '관심 있음' }));
    let items = await cards();
    expect(items).toHaveLength(1);
    expect(within(at(items, 0)).getByText('관심 있음 표시함')).toBeInTheDocument();
    expect(screen.getByText('3개 중 1개 표시')).toBeInTheDocument();

    fireEvent.click(filters.getByRole('button', { name: '피드백 없음' }));
    items = await cards();
    expect(items).toHaveLength(1);
    expect(within(at(items, 0)).getByText(/1위/)).toBeInTheDocument();

    fireEvent.click(filters.getByRole('button', { name: '전체' }));
    expect(await cards()).toHaveLength(3);
  });

  it('sends the user back to login when the API answers 401 (session expired)', async () => {
    setRecommendationMockScenario({ latest: 'unauthorized' });
    setup('/recommendations');
    await signIn();
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '맞춤 공고 추천' })).not.toBeInTheDocument();
  });

  it('has a 맞춤 추천 link in the sidebar navigation', async () => {
    await openRecommendations();
    expect(screen.getByRole('link', { name: '맞춤 추천' })).toHaveAttribute('href', '/recommendations');
  });
});
