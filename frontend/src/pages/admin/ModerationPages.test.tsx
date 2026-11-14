import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationServiceProvider } from '../../admin/ModerationServiceProvider';
import { ApiError } from '../../api/errors';
import { AuthContext, type AuthContextValue } from '../../auth/useAuth';
import { MOCK_ADMIN_ID, createMockModerationService, type MockModerationService } from '../../mocks/moderation';
import { ModerationCasePage } from './ModerationCasePage';
import { ModerationQueuePage } from './ModerationQueuePage';

// 이 파일은 Mock Adapter 화면 시험입니다(실제 API 경로는 admin/ModerationServiceProvider.test.tsx).
vi.mock('../../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: true } }));

let fetchSpy: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => {
  fetchSpy = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetchSpy);
});
afterEach(() => {
  const calls = fetchSpy.mock.calls.length;
  vi.unstubAllGlobals();
  // 모든 테스트 공통 가드: T81 전에는 검수 화면이 네트워크 요청을 보내면 안 됩니다.
  if (calls) throw new Error(`the moderation UI sent ${calls} network request(s); it must use the mock adapter only`);
});

function setup(path: string, options: { latencyMs?: number; cases?: Parameters<typeof createMockModerationService>[0]['cases'] } = {}) {
  const service: MockModerationService = createMockModerationService({ viewer: () => MOCK_ADMIN_ID, ...options });
  const auth: AuthContextValue = {
    state: { status: 'authenticated', token: 'synthetic', user: { email: MOCK_ADMIN_ID, displayName: '합성 관리자',
      roles: ['job_seeker', 'admin'], userId: MOCK_ADMIN_ID } },
    login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(), googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
  };
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<ModerationServiceProvider service={service} />}>
            <Route path="/admin/moderation" element={<ModerationQueuePage />} />
            <Route path="/admin/moderation/:caseId" element={<ModerationCasePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  return service;
}

const rows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1);
const button = (name: string) => screen.getByRole('button', { name });
const facts = () => screen.getByRole('heading', { level: 1 }).parentElement!.querySelector('dl')!;
const decideCalls = (s: MockModerationService) => s.calls.filter((c) => c.method === 'decide').length;

describe('queue', () => {
  it('lists cases with status text, priority, due date, assignee and the mock notice', async () => {
    setup('/admin/moderation');
    expect(await screen.findByRole('table', { name: '검수 건 목록' })).toBeInTheDocument();
    expect(rows()).toHaveLength(9);
    expect(screen.getByRole('note')).toHaveTextContent('가상 데이터(Mock)');
    const first = rows()[0]!;
    expect(first).toHaveTextContent('P1 긴급');
    expect(first).toHaveTextContent('대기');
    expect(first).toHaveTextContent('기한 초과');
    expect(first).toHaveTextContent('미배정');
    expect(screen.getByRole('link', { name: /mc-00003/ }).closest('tr')).toHaveTextContent(`나 (${MOCK_ADMIN_ID})`);
    expect(screen.queryByText(/owner-1@example\.invalid/)).not.toBeInTheDocument();
  });

  it('filters by status, priority and content type', async () => {
    setup('/admin/moderation');
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: '반려' }));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0]).toHaveTextContent('mc-00008');
    fireEvent.click(screen.getAllByRole('button', { name: '전체' })[0]!);
    fireEvent.change(screen.getByLabelText('콘텐츠 유형'), { target: { value: 'company' } });
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0]).toHaveTextContent('mc-00006');
    fireEvent.change(screen.getByLabelText('콘텐츠 유형'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'P3 게시 전' }));
    await waitFor(() => expect(rows()).toHaveLength(3));
  });

  it('shows the empty state', async () => {
    setup('/admin/moderation', { cases: [] });
    expect(await screen.findByText('검수 건 목록: 데이터가 없습니다')).toBeInTheDocument();
  });

  it('shows an API error and recovers with retry', async () => {
    const service = createMockModerationService({ viewer: () => MOCK_ADMIN_ID });
    service.failNext(new ApiError(503, '/v1/admin/moderation-cases'));
    const auth: AuthContextValue = { state: { status: 'authenticated', token: 't', user: { email: MOCK_ADMIN_ID,
      displayName: '합성 관리자', roles: ['admin'], userId: MOCK_ADMIN_ID } }, login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(), googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>() };
    render(<AuthContext.Provider value={auth}><MemoryRouter initialEntries={['/admin/moderation']}><Routes>
      <Route element={<ModerationServiceProvider service={service} />}>
        <Route path="/admin/moderation" element={<ModerationQueuePage />} />
      </Route></Routes></MemoryRouter></AuthContext.Provider>);
    expect(await screen.findByText('검수 건 목록 불러오기 실패')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });

  it('opens a case from the list', async () => {
    setup('/admin/moderation');
    fireEvent.click(await screen.findByRole('link', { name: /mc-00008/ }));
    expect(await screen.findByRole('heading', { name: '검수 건 mc-00008' })).toBeInTheDocument();
  });
});

describe('case detail', () => {
  it('shows target, request reason, status, flags, deadline, assignee and history', async () => {
    setup('/admin/moderation/mc-00001');
    await screen.findByRole('heading', { name: '검수 건 mc-00001' });
    expect(facts()).toHaveTextContent('채용공고 · [합성] 백엔드 신입 채용공고');
    expect(facts()).toHaveTextContent('신고 (신고 3건)');
    expect(facts()).toHaveTextContent('대기');
    expect(facts()).toHaveTextContent('미배정');
    expect(screen.getByText('개인정보 패턴 의심')).toBeInTheDocument();
    expect(facts()).toHaveTextContent(/처리 기한.*\(기한 초과\)/);
    expect(facts()).toHaveTextContent('P1 긴급');
    expect(screen.getByRole('heading', { name: '처리 이력' }).nextElementSibling).toHaveTextContent('접수');
  });

  it('shows rejection reason and decision for a rejected case, and close reason for a closed case', async () => {
    setup('/admin/moderation/mc-00008');
    await screen.findByRole('heading', { name: '검수 건 mc-00008' });
    expect(facts()).toHaveTextContent('유해 (HARMFUL)');
    expect(button('승인')).toBeDisabled();
    expect(screen.getAllByText('이미 결정된 검수 건입니다.').length).toBeGreaterThan(0);
  });

  it('closed case: close reason shown, every action disabled', async () => {
    setup('/admin/moderation/mc-00009');
    await screen.findByRole('heading', { name: '검수 건 mc-00009' });
    expect(facts()).toHaveTextContent('대상 삭제');
    for (const name of ['담당 시작', '승인', '반려']) expect(button(name)).toBeDisabled();
  });

  it('404 for an unknown case', async () => {
    setup('/admin/moderation/mc-unknown');
    expect(await screen.findByText('검수 건을 찾을 수 없습니다.')).toBeInTheDocument();
  });
});

describe('actions', () => {
  it('assigns the case to me', async () => {
    const service = setup('/admin/moderation/mc-00001');
    await screen.findByRole('heading', { name: '검수 건 mc-00001' });
    fireEvent.click(button('담당 시작'));
    expect(await screen.findByRole('status')).toHaveTextContent('담당을 시작했습니다.');
    expect(facts()).toHaveTextContent('검수 중');
    expect(facts()).toHaveTextContent(`나 (${MOCK_ADMIN_ID})`);
    expect(screen.getByRole('heading', { name: '처리 이력' }).nextElementSibling).toHaveTextContent('담당 시작');
    expect(button('승인')).toBeEnabled();
    expect(service.calls.filter((c) => c.method === 'assign')).toHaveLength(1);
  });

  it('approves after confirmation and becomes read-only', async () => {
    setup('/admin/moderation/mc-00003');
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    fireEvent.click(button('승인'));
    const dialog = screen.getByRole('dialog', { name: '이 검수 건을 승인할까요?' });
    fireEvent.click(within(dialog).getByRole('button', { name: '승인' }));
    expect(await screen.findByRole('status')).toHaveTextContent('승인했습니다.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(facts()).toHaveTextContent('승인');
    for (const name of ['담당 시작', '승인', '반려']) expect(button(name)).toBeDisabled();
  });

  it('rejects with a reason code and shows it in the details and history', async () => {
    setup('/admin/moderation/mc-00003');
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    fireEvent.click(button('반려'));
    const dialog = screen.getByRole('dialog', { name: '이 검수 건을 반려할까요?' });
    expect(within(dialog).getByLabelText('반려 사유 (필수)')).toHaveFocus();
    fireEvent.change(within(dialog).getByLabelText('반려 사유 (필수)'), { target: { value: 'DUPLICATE' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '반려' }));
    expect(await screen.findByRole('status')).toHaveTextContent('반려했습니다.');
    expect(facts()).toHaveTextContent('중복 (DUPLICATE)');
    expect(screen.getByRole('heading', { name: '처리 이력' }).nextElementSibling).toHaveTextContent('사유 DUPLICATE');
  });

  it('blocks a missing reason and OTHER without a note before sending anything', async () => {
    const service = setup('/admin/moderation/mc-00003');
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    fireEvent.click(button('반려'));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '반려' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('반려 사유를 선택해 주세요.');
    expect(within(dialog).getByLabelText('반려 사유 (필수)')).toHaveAttribute('aria-invalid', 'true');
    fireEvent.change(within(dialog).getByLabelText('반려 사유 (필수)'), { target: { value: 'OTHER' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '반려' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('기타(OTHER) 사유는 설명을 입력해야 합니다.');
    const note = within(dialog).getByLabelText('설명 (필수)');
    expect(note).toHaveAttribute('aria-describedby', within(dialog).getByRole('alert').id);
    expect(decideCalls(service)).toBe(0);
    fireEvent.change(note, { target: { value: '합성 사유 설명' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '반려' }));
    expect(await screen.findByRole('status')).toHaveTextContent('반려했습니다.');
    expect(decideCalls(service)).toBe(1);
  });

  it('Escape closes the dialog and returns focus to the button', async () => {
    setup('/admin/moderation/mc-00003');
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    const approve = button('승인');
    approve.focus();
    fireEvent.click(approve);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(approve).toHaveFocus();
  });
});

describe('boundaries (UI disables; the mock server also refuses)', () => {
  it('own content cannot be taken', async () => {
    setup('/admin/moderation/mc-00002');
    await screen.findByRole('heading', { name: '검수 건 mc-00002' });
    expect(button('담당 시작')).toBeDisabled();
    expect(button('담당 시작')).toHaveAccessibleDescription('자기 콘텐츠는 검수할 수 없습니다.');
  });

  it('another admin\'s case cannot be decided by me', async () => {
    setup('/admin/moderation/mc-00004');
    await screen.findByRole('heading', { name: '검수 건 mc-00004' });
    expect(button('승인')).toBeDisabled();
    expect(button('승인')).toHaveAccessibleDescription('담당자만 승인·반려할 수 있습니다.');
  });

  it('the first decider cannot take the appeal review; another case is open to me', async () => {
    setup('/admin/moderation/mc-00005');
    await screen.findByRole('heading', { name: '검수 건 mc-00005' });
    expect(facts()).toHaveTextContent('이의제기 재검토 단계');
    expect(button('담당 시작')).toHaveAccessibleDescription(/최초 결정자가 아닌/);
  });

  it('an approved case cannot be processed again', async () => {
    setup('/admin/moderation/mc-00007');
    await screen.findByRole('heading', { name: '검수 건 mc-00007' });
    for (const name of ['담당 시작', '승인', '반려']) expect(button(name)).toBeDisabled();
  });
});

describe('server errors and conflicts', () => {
  it('403 from the server is shown', async () => {
    const service = setup('/admin/moderation/mc-00001');
    await screen.findByRole('heading', { name: '검수 건 mc-00001' });
    service.failNext(new ApiError(403, 'x', undefined, 'FORBIDDEN'));
    fireEvent.click(button('담당 시작'));
    expect(await screen.findByRole('alert')).toHaveTextContent('이 검수 건을 처리할 권한이 없습니다.');
  });

  it('422 from the server is shown', async () => {
    const service = setup('/admin/moderation/mc-00003');
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    service.failNext(new ApiError(422, 'x', undefined, 'VALIDATION_FAILED'));
    fireEvent.click(button('반려'));
    fireEvent.change(screen.getByLabelText('반려 사유 (필수)'), { target: { value: 'HARMFUL' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '반려' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('입력값을 확인해 주세요.');
  });

  it('409 conflict (stale version) offers reloading, then the action works on fresh data', async () => {
    const service = setup('/admin/moderation/mc-00003');
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    service.touch('mc-00003');
    fireEvent.click(button('승인'));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '승인' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('다른 관리자가 먼저 이 건을 바꿨습니다.');
    fireEvent.click(button('최신 내용 다시 불러오기'));
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(button('승인'));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '승인' }));
    expect(await screen.findByRole('status')).toHaveTextContent('승인했습니다.');
  });

  it('a failed request can be retried', async () => {
    const service = setup('/admin/moderation/mc-00001');
    await screen.findByRole('heading', { name: '검수 건 mc-00001' });
    service.failNext(new ApiError(503, 'x'));
    fireEvent.click(button('담당 시작'));
    expect(await screen.findByRole('alert')).toHaveTextContent('잠시 후 다시 시도해 주세요.');
    fireEvent.click(button('담당 시작'));
    expect(await screen.findByRole('status')).toHaveTextContent('담당을 시작했습니다.');
  });
});

describe('no network before T81', () => {
  it('a full assign → approve flow uses only the in-memory adapter', async () => {
    setup('/admin/moderation/mc-00001');
    await screen.findByRole('heading', { name: '검수 건 mc-00001' });
    fireEvent.click(button('담당 시작'));
    await screen.findByRole('status');
    fireEvent.click(button('승인'));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '승인' }));
    expect(await screen.findByRole('status')).toHaveTextContent('승인했습니다.');
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('double submission', () => {
  it('approve: rapid double click sends one request and buttons are disabled while pending', async () => {
    const service = setup('/admin/moderation/mc-00003', { latencyMs: 60 });
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    fireEvent.click(button('승인'));
    const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: '승인' });
    act(() => { confirm.click(); confirm.click(); });
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: '처리 중…' })).toBeDisabled();
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: '취소' })).toBeDisabled();
    expect(button('반려')).toBeDisabled();
    expect(await screen.findByRole('status')).toHaveTextContent('승인했습니다.');
    expect(decideCalls(service)).toBe(1);
  });

  it('reject: rapid double click sends one request', async () => {
    const service = setup('/admin/moderation/mc-00003', { latencyMs: 60 });
    await screen.findByRole('heading', { name: '검수 건 mc-00003' });
    fireEvent.click(button('반려'));
    fireEvent.change(screen.getByLabelText('반려 사유 (필수)'), { target: { value: 'EXPIRED' } });
    const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: '반려' });
    act(() => { confirm.click(); confirm.click(); });
    expect(await screen.findByRole('status')).toHaveTextContent('반려했습니다.');
    expect(decideCalls(service)).toBe(1);
  });

  it('assign: rapid double click sends one request', async () => {
    const service = setup('/admin/moderation/mc-00001', { latencyMs: 60 });
    await screen.findByRole('heading', { name: '검수 건 mc-00001' });
    const assign = button('담당 시작');
    act(() => { assign.click(); assign.click(); });
    expect(button('담당 시작')).toBeDisabled();
    expect(await screen.findByRole('status')).toHaveTextContent('담당을 시작했습니다.');
    expect(service.calls.filter((c) => c.method === 'assign')).toHaveLength(1);
  });
});
