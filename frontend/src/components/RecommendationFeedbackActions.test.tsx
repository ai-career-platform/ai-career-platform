import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import {
  recommendationMockLog,
  resetRecommendationMock,
  setRecommendationMockScenario,
} from '../mocks/recommendations';
import { routes } from '../routes';

// T45 추천 실행 API 가 머지되지 않았으므로 추천·피드백 호출을 모두 Mock 으로 처리한다 (PARTIAL).
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

const RUN_ID = '00000000-0000-4000-8000-000000000a01';
const POSTING_1 = '00000000-0000-4000-8000-000000000101';
const TITLE_1 = '백엔드 개발자 (신입)';
const TITLE_2 = 'Python 서버 개발자';
const TITLE_3 = '데이터 엔지니어 (주니어)';

async function openRecommendations() {
  const router = createMemoryRouter(routes, { initialEntries: ['/recommendations'] });
  render(<RouterProvider router={router} />);
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: 'user@example.com' } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
  await screen.findByRole('list', { name: '추천 공고 목록' });
  return router;
}

/** 공고 제목으로 카드의 피드백 버튼 묶음을 찾는다. */
const feedbackGroup = (title: string) => within(screen.getByRole('group', { name: `${title} 피드백` }));
const toggle = (title: string, name: '관심 있음' | '관심 없음') => feedbackGroup(title).getByRole('button', { name });
const card = (title: string) => {
  const element = screen.getByRole('group', { name: `${title} 피드백` }).closest('li');
  if (!element) throw new Error(`card ${title} not found`);
  return within(element);
};
const feedbackPosts = () =>
  recommendationMockLog.filter((entry) => entry.method === 'POST' && entry.path === '/v1/recommendation-feedback');
const runGets = () => recommendationMockLog.filter((entry) => entry.method === 'GET' && entry.path === `/v1/recommendation-runs/${RUN_ID}`);

beforeEach(() => resetRecommendationMock());
afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe('추천 피드백 버튼 (T48, FR-ANL-004)', () => {
  it('shows my previous feedback as pressed toggles and offers a cancel path only when feedback exists', async () => {
    await openRecommendations();

    expect(toggle(TITLE_1, '관심 있음')).toHaveAttribute('aria-pressed', 'false');
    expect(toggle(TITLE_1, '관심 없음')).toHaveAttribute('aria-pressed', 'false');
    expect(feedbackGroup(TITLE_1).queryByRole('button', { name: '피드백 취소' })).not.toBeInTheDocument();

    expect(toggle(TITLE_2, '관심 있음')).toHaveAttribute('aria-pressed', 'true');
    expect(card(TITLE_2).getByText('관심 있음 표시함')).toBeInTheDocument();
    expect(feedbackGroup(TITLE_2).getByRole('button', { name: '피드백 취소' })).toBeInTheDocument();

    expect(toggle(TITLE_3, '관심 없음')).toHaveAttribute('aria-pressed', 'true');
    expect(card(TITLE_3).getByText('관심 없음 표시함')).toBeInTheDocument();
  });

  it('saves liked with the contract body, blocks double submission while pending, then re-fetches the run', async () => {
    await openRecommendations();

    fireEvent.click(toggle(TITLE_1, '관심 있음'));
    fireEvent.click(toggle(TITLE_1, '관심 있음'));
    fireEvent.click(toggle(TITLE_1, '관심 없음'));

    expect(toggle(TITLE_1, '관심 있음')).toBeDisabled();
    expect(toggle(TITLE_1, '관심 없음')).toBeDisabled();
    expect(screen.getByRole('group', { name: `${TITLE_1} 피드백` })).toHaveAttribute('aria-busy', 'true');
    expect(card(TITLE_1).getByRole('status')).toHaveTextContent('피드백을 저장하는 중입니다');

    await waitFor(() => expect(toggle(TITLE_1, '관심 있음')).toHaveAttribute('aria-pressed', 'true'));
    expect(toggle(TITLE_1, '관심 있음')).toBeEnabled();
    expect(card(TITLE_1).getByText('관심 있음 표시함')).toBeInTheDocument();
    expect(card(TITLE_1).getByRole('status')).toHaveTextContent('관심 있음으로 저장했어요.');

    // 한 번만 전송되고, 저장 뒤 같은 추천 실행을 다시 조회한다 (DoD: 저장 후 상태 재조회).
    expect(feedbackPosts()).toHaveLength(1);
    expect(feedbackPosts()[0]?.body).toEqual({ recommendation_run_id: RUN_ID, job_posting_id: POSTING_1, feedback: 'liked' });
    expect(runGets()).toHaveLength(1);
    const postIndex = recommendationMockLog.indexOf(feedbackPosts()[0]!);
    expect(recommendationMockLog.indexOf(runGets()[0]!)).toBeGreaterThan(postIndex);
  });

  it('lets the user correct the value and cancel it (cleared)', async () => {
    await openRecommendations();

    fireEvent.click(toggle(TITLE_2, '관심 없음'));
    await waitFor(() => expect(toggle(TITLE_2, '관심 없음')).toHaveAttribute('aria-pressed', 'true'));
    expect(toggle(TITLE_2, '관심 있음')).toHaveAttribute('aria-pressed', 'false');
    expect(card(TITLE_2).getByText('관심 없음 표시함')).toBeInTheDocument();
    expect(card(TITLE_2).getByRole('status')).toHaveTextContent('다음 추천부터 이 공고는 제외돼요');

    fireEvent.click(feedbackGroup(TITLE_2).getByRole('button', { name: '피드백 취소' }));
    await waitFor(() => expect(toggle(TITLE_2, '관심 없음')).toHaveAttribute('aria-pressed', 'false'));
    expect(toggle(TITLE_2, '관심 있음')).toHaveAttribute('aria-pressed', 'false');
    expect(card(TITLE_2).queryByText(/표시함$/)).not.toBeInTheDocument();
    expect(feedbackGroup(TITLE_2).queryByRole('button', { name: '피드백 취소' })).not.toBeInTheDocument();
    expect(card(TITLE_2).getByRole('status')).toHaveTextContent('피드백을 취소했어요.');

    expect(feedbackPosts().map((entry) => (entry.body as { feedback: string }).feedback)).toEqual(['not_interested', 'cleared']);
  });

  it('sends cleared when the pressed toggle is pressed again', async () => {
    await openRecommendations();
    fireEvent.click(toggle(TITLE_2, '관심 있음'));
    await waitFor(() => expect(toggle(TITLE_2, '관심 있음')).toHaveAttribute('aria-pressed', 'false'));
    expect(feedbackPosts()[0]?.body).toMatchObject({ feedback: 'cleared' });
  });

  it('shows an error with retry and keeps the stored state when saving fails', async () => {
    setRecommendationMockScenario({ feedback: 'error' });
    await openRecommendations();

    fireEvent.click(toggle(TITLE_1, '관심 없음'));
    expect(await card(TITLE_1).findByRole('alert')).toHaveTextContent('피드백을 저장하지 못했습니다');
    expect(toggle(TITLE_1, '관심 없음')).toHaveAttribute('aria-pressed', 'false');
    expect(toggle(TITLE_1, '관심 없음')).toBeEnabled();
    expect(runGets()).toHaveLength(0);

    setRecommendationMockScenario({ feedback: 'saved' });
    fireEvent.click(card(TITLE_1).getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(toggle(TITLE_1, '관심 없음')).toHaveAttribute('aria-pressed', 'true'));
    expect(card(TITLE_1).queryByRole('alert')).not.toBeInTheDocument();
    expect(feedbackPosts().map((entry) => (entry.body as { feedback: string }).feedback)).toEqual(['not_interested', 'not_interested']);
  });

  it.each([
    ['notFound', 404],
    ['invalid', 422],
  ] as const)('shows a non-retryable message without a retry button when saving answers %s (%i)', async (feedback, _status) => {
    setRecommendationMockScenario({ feedback });
    await openRecommendations();

    fireEvent.click(toggle(TITLE_1, '관심 있음'));
    const alert = await card(TITLE_1).findByRole('alert');
    expect(alert).toHaveTextContent('이 공고에는 피드백을 남길 수 없습니다. 추천을 새로 받아 주세요.');
    expect(alert).not.toHaveTextContent('잠시 후 다시 시도해 주세요');
    expect(card(TITLE_1).queryByRole('button', { name: '다시 시도' })).not.toBeInTheDocument();
    expect(toggle(TITLE_1, '관심 있음')).toHaveAttribute('aria-pressed', 'false');
    expect(toggle(TITLE_1, '관심 있음')).toBeEnabled();
    expect(feedbackPosts()).toHaveLength(1);
    expect(runGets()).toHaveLength(0);
  });

  it('falls back to the saved response when only the re-fetch fails', async () => {
    setRecommendationMockScenario({ runById: 'error' });
    await openRecommendations();

    fireEvent.click(toggle(TITLE_1, '관심 있음'));
    await waitFor(() => expect(toggle(TITLE_1, '관심 있음')).toHaveAttribute('aria-pressed', 'true'));
    expect(card(TITLE_1).queryByRole('alert')).not.toBeInTheDocument();
    expect(runGets()).toHaveLength(1);
  });

  it('excludes a not_interested posting from the next recommendation run', async () => {
    await openRecommendations();
    fireEvent.click(toggle(TITLE_1, '관심 없음'));
    await waitFor(() => expect(toggle(TITLE_1, '관심 없음')).toHaveAttribute('aria-pressed', 'true'));

    fireEvent.click(screen.getByRole('button', { name: '새 추천 받기' }));
    expect(await screen.findByRole('button', { name: '새 추천 받기' })).toBeEnabled();
    await waitFor(() => expect(screen.queryByRole('group', { name: `${TITLE_1} 피드백` })).not.toBeInTheDocument());
    expect(screen.queryByRole('group', { name: `${TITLE_3} 피드백` })).not.toBeInTheDocument();
    expect(toggle(TITLE_2, '관심 있음')).toHaveAttribute('aria-pressed', 'true');
  });

  it('sends the user to login when saving feedback answers 401', async () => {
    setRecommendationMockScenario({ feedback: 'unauthorized' });
    await openRecommendations();
    fireEvent.click(toggle(TITLE_1, '관심 있음'));
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
  });

  it('never says feedback is shared with companies and tells what it is used for', async () => {
    await openRecommendations();
    expect(card(TITLE_1).getByText('피드백은 내 추천 개선에만 사용돼요.')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/기업에 (제공|공유)|고용주|채용 담당자/);
  });
});

describe('추천 설명 대화상자 (T48, F-018)', () => {
  const openDialog = (title = TITLE_1) => {
    const trigger = screen.getByRole('button', { name: `${title} 추천 설명 보기` });
    trigger.focus();
    fireEvent.click(trigger);
    return { trigger, dialog: screen.getByRole('dialog', { name: `${title} 추천 설명` }) };
  };

  it('is a labelled modal dialog with the reason, basis and a no-skill-gap state, and moves focus inside', async () => {
    await openRecommendations();
    const { trigger, dialog } = openDialog();

    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleDescription(/AI의 확정 판단이 아닙니다/);
    expect(within(dialog).getByRole('button', { name: '추천 설명 닫기' })).toHaveFocus();

    const view = within(dialog);
    expect(view.getByText(/Python·SQL 요구 기술을 보유/)).toBeInTheDocument();
    expect(view.getByText('match_rule v1 (규칙 기반)')).toBeInTheDocument();
    expect(view.getByText('맞춤 추천')).toBeInTheDocument();
    expect(view.getByText('82 / 100')).toBeInTheDocument();
    expect(view.getByText(/합격 가능성\(확률\)이 아닙니다/)).toBeInTheDocument();
    expect(view.getByText(/부족 역량 정보 없음/)).toHaveTextContent('추후 제공');
    expect(view.getByText('피드백은 내 추천 개선에만 사용돼요.')).toBeInTheDocument();
    expect(view.queryByRole('note')).not.toBeInTheDocument();
  });

  it('closes on Escape and returns focus to the opener', async () => {
    await openRecommendations();
    const { trigger, dialog } = openDialog();

    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('keeps Tab focus inside the dialog', async () => {
    await openRecommendations();
    const { dialog } = openDialog();
    const close = within(dialog).getByRole('button', { name: '추천 설명 닫기' });
    const footerClose = within(dialog).getByRole('button', { name: '닫기' });

    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(footerClose).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(close).toHaveFocus();
  });

  it('keeps Escape and the Tab trap working after focus leaves to the body (clicking plain text)', async () => {
    await openRecommendations();
    const { trigger, dialog } = openDialog();
    const close = within(dialog).getByRole('button', { name: '추천 설명 닫기' });
    const footerClose = within(dialog).getByRole('button', { name: '닫기' });

    // 대화상자는 tabIndex=-1 이라 안쪽 글자를 눌러도 초점을 받을 수 있다
    expect(dialog).toHaveAttribute('tabindex', '-1');

    // 초점이 body 로 빠져도 Tab·Shift+Tab 은 대화상자 안으로 되돌아온다
    close.blur();
    expect(document.body).toHaveFocus();
    fireEvent.keyDown(document.body, { key: 'Tab' });
    expect(close).toHaveFocus();
    close.blur();
    fireEvent.keyDown(document.body, { key: 'Tab', shiftKey: true });
    expect(footerClose).toHaveFocus();

    // 대화상자 자체에 초점이 있을 때도 Tab 은 첫 요소로 간다
    dialog.focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(close).toHaveFocus();

    // body 에서 Esc 를 눌러도 닫히고 연 버튼으로 초점이 돌아온다
    close.blur();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes with the close button and with a backdrop click', async () => {
    await openRecommendations();
    let { trigger, dialog } = openDialog();
    fireEvent.click(within(dialog).getByRole('button', { name: '닫기' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    ({ trigger, dialog } = openDialog(TITLE_2));
    fireEvent.mouseDown(dialog);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId('recommendation-dialog-backdrop'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('marks a fallback run as not personalized and shows no score', async () => {
    setRecommendationMockScenario({ latest: 'fallback' });
    await openRecommendations();
    const { dialog } = openDialog(TITLE_1);
    const view = within(dialog);

    expect(view.getByRole('note')).toHaveTextContent('기준 추천(개인화 아님)');
    expect(view.getByText('기준 추천 (개인화 아님)')).toBeInTheDocument();
    expect(view.getByText('latest_postings v1 (규칙 기반)')).toBeInTheDocument();
    expect(view.getByText('점수 없음')).toBeInTheDocument();
    expect(view.getByRole('heading', { name: '표시 이유' })).toBeInTheDocument();
    expect(view.queryByText(/합격 가능성/)).not.toBeInTheDocument();
  });
});
