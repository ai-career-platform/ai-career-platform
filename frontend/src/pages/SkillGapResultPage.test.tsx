import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { AuthContext, type AuthContextValue, type AuthState } from '../auth/useAuth';
import { SkillGapResultPage } from './SkillGapResultPage';

const result = {
  assessment_id: 'assessment-1',
  job_role: { job_role_id: 'role-1', code: 'BACKEND', name: '백엔드 개발자' },
  model_version: { model_code: 'test', version: '1', kind: 'rule' as const },
  is_stale: true, evaluated_at: '2026-11-09T00:00:00Z',
  items: [{ skill: { skill_id: 'skill-1', code: 'PYTHON', name: 'Python' }, required_level: 5, observed_level: 3, gap: 2 }],
};
const authenticated: AuthState = { status: 'authenticated', token: 'test-only', user: { email: 'test@example.test', displayName: '테스트', roles: [] } };

function setup(jobRoleId?: string, assessmentId?: string) {
  const request = vi.fn<AuthContextValue['request']>();
  const value: AuthContextValue = {
    state: authenticated, login: vi.fn(), logout: vi.fn(),
    request: async <T,>(path: string, options?: Parameters<AuthContextValue['request']>[1]) => await request(path, options) as T,
  };
  const view = (state: AuthState = authenticated, role = jobRoleId) => <AuthContext.Provider value={{ ...value, state }}><SkillGapResultPage jobRoleId={role} assessmentId={assessmentId} /></AuthContext.Provider>;
  return { request, view };
}

describe('실제 요청 상태에 따른 T44 화면', () => {
  it('로그인 전에는 요청하지 않고 인증 필요 화면을 표시한다', () => {
    const { request, view } = setup();
    render(view({ status: 'anonymous' }));
    expect(screen.getByText('로그인이 필요합니다')).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByText(/가상 데이터 미리보기/)).not.toBeInTheDocument();
  });

  it('요청 중 로딩, 이력과 상세 응답 후 결과 및 stale 안내를 자동 표시한다', async () => {
    const { request, view } = setup('role-1');
    let resolve!: (value: unknown) => void;
    request.mockReturnValueOnce(new Promise((done) => { resolve = done; })).mockResolvedValueOnce(result);
    render(view());
    expect(screen.getByText('분석 결과를 불러오는 중입니다')).toBeInTheDocument();
    await act(async () => { resolve({ items: [{ assessment_id: 'assessment-1' }], next_cursor: null }); });
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(screen.getByText(/이전 입력으로/)).toBeInTheDocument();
    expect(request.mock.calls[0]![0]).toBe('/v1/skill-gaps?job_role_id=role-1&limit=1');
    expect(request.mock.calls[1]![0]).toBe('/v1/skill-gaps/assessment-1');
  });

  it('빈 이력에서는 결과 없음, 선택 직무가 없으면 분석 비활성화를 표시한다', async () => {
    const { request, view } = setup();
    request.mockResolvedValue({ items: [], next_cursor: null });
    render(view());
    expect(await screen.findByText('아직 분석 결과가 없습니다')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '분석하기' })).toBeDisabled();
    expect(screen.getByRole('link', { name: '목표 직무 관리' })).toHaveAttribute('href', '/me/target-roles');
  });

  it('조회 실패를 표시하고 재시도 성공 시 빈 결과로 전환한다', async () => {
    const { request, view } = setup('role-1');
    request.mockRejectedValueOnce(new ApiError(503, '/v1/skill-gaps')).mockResolvedValueOnce({ items: [], next_cursor: null });
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('불러오지 못했습니다');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('아직 분석 결과가 없습니다')).toBeInTheDocument();
  });

  it('빈 이력에서 선택 직무를 처음 분석하고 완료 전 중복 요청을 차단한다', async () => {
    const { request, view } = setup('role-1');
    let resolve!: (value: unknown) => void;
    request.mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    render(view());
    const button = await screen.findByRole('button', { name: '분석하기' });
    fireEvent.click(button);
    expect(screen.getByRole('button', { name: '분석 중…' })).toBeDisabled();
    fireEvent.click(button);
    expect(request).toHaveBeenCalledTimes(2);
    await act(async () => { resolve(result); });
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('401 응답을 받으면 인증 필요 상태로 전환한다', async () => {
    const { request, view } = setup();
    request.mockRejectedValueOnce(new ApiError(401, '/v1/skill-gaps'));
    render(view());
    expect(await screen.findByText('로그인이 필요합니다')).toBeInTheDocument();
  });

  it('지정 결과 404는 빈 이력이 아닌 조회 실패로 표시한다', async () => {
    const { request, view } = setup(undefined, 'missing');
    request.mockRejectedValueOnce(new ApiError(404, '/v1/skill-gaps/missing'));
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('불러오지 못했습니다');
  });

  it('분석 POST가 실패하면 이전 결과를 보존하고 성공하면 새 결과로 교체한다', async () => {
    const { request, view } = setup('role-1', 'assessment-1');
    request.mockResolvedValueOnce(result).mockRejectedValueOnce(new ApiError(503, '/v1/skill-gaps'))
      .mockResolvedValueOnce({ ...result, is_stale: false, items: [{ ...result.items[0], observed_level: 5, gap: 0 }] });
    render(view());
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: '재분석' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('이전 결과');
    expect(screen.getByRole('table')).toHaveTextContent('Python');
    fireEvent.click(screen.getByRole('button', { name: '재분석' }));
    expect(await screen.findByText('0개')).toBeInTheDocument();
    expect(screen.queryByText(/이전 입력으로/)).not.toBeInTheDocument();
    expect(request).toHaveBeenLastCalledWith('/v1/skill-gaps', { method: 'POST', body: { job_role_id: 'role-1' } });
  });

  it('직무를 바꾼 뒤 도착하는 이전 응답은 표시하지 않는다', async () => {
    const { request, view } = setup('role-1', 'assessment-1');
    let resolve!: (value: unknown) => void;
    request.mockReturnValueOnce(new Promise((done) => { resolve = done; }))
      .mockResolvedValueOnce({ ...result, job_role: { ...result.job_role, job_role_id: 'role-2', name: '새 직무' } });
    const { rerender } = render(view());
    rerender(view(authenticated, 'role-2'));
    await screen.findByText('새 직무');
    await act(async () => { resolve(result); });
    expect(screen.queryByText('백엔드 개발자')).not.toBeInTheDocument();
  });

  it('로그아웃 즉시 기존 표를 숨긴다', async () => {
    const { request, view } = setup(undefined, 'assessment-1');
    request.mockResolvedValue(result);
    const { rerender } = render(view());
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
    rerender(view({ status: 'anonymous' }));
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('로그인이 필요합니다')).toBeInTheDocument();
  });
});
