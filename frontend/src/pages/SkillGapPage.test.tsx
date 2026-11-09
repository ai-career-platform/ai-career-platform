import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SkillGapPage } from './SkillGapPage';
import type { SkillGap } from '../api/skillGaps';

// Synthetic input stays in tests; production components never import it.
export const skillGapPreviewResult: SkillGap = {
  assessment_id: '00000000-0000-4000-8000-000000000001',
  job_role: { job_role_id: '00000000-0000-4000-8000-000000000002', code: 'BACKEND_ENGINEER', name: '백엔드 개발자' },
  model_version: { model_code: 'test_rule', version: 'test', kind: 'rule' },
  is_stale: false,
  evaluated_at: '2026-11-09T00:00:00Z',
  items: [
    { skill: { skill_id: '00000000-0000-4000-8000-000000000003', code: 'PYTHON', name: 'Python' }, required_level: 5, observed_level: 3, gap: 2 },
    { skill: { skill_id: '00000000-0000-4000-8000-000000000004', code: 'SQL', name: 'SQL' }, required_level: 3, observed_level: 0, gap: 3 },
    { skill: { skill_id: '00000000-0000-4000-8000-000000000005', code: 'GIT', name: 'Git' }, required_level: 2, observed_level: 4, gap: 0 },
  ],
};

describe('T44 Skill Gap 결과', () => {
  it('수준과 근거를 표시하고 원본을 변경하지 않고 부족 수준 순서로 정렬한다', () => {
    const original = structuredClone(skillGapPreviewResult);
    render(<SkillGapPage status={{ state: 'ready', result: skillGapPreviewResult }} />);
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('SQL');
    expect(rows[2]).toHaveTextContent('Python');
    expect(rows[3]).toHaveTextContent('Git');
    expect(rows[1]).toHaveTextContent('미입력 포함');
    expect(rows[3]).toHaveTextContent('충족');
    expect(screen.getByText(/규칙 기반/)).toBeInTheDocument();
    expect(screen.getByText(/미등록·미평가/)).toBeInTheDocument();
    expect(skillGapPreviewResult).toEqual(original);
    expect(screen.getByRole('button', { name: '재분석' })).toBeDisabled();
  });

  it('같은 부족 수준은 기술 코드 순서로 표시한다', () => {
    const items = skillGapPreviewResult.items.slice(0, 2).map((item) => ({ ...item, observed_level: item.required_level - 2, gap: 2 }));
    render(<SkillGapPage status={{ state: 'ready', result: { ...skillGapPreviewResult, items: items.reverse() } }} />);
    expect(within(screen.getByRole('table')).getAllByRole('row')[1]).toHaveTextContent('Python');
    expect(screen.getByText(/같은 우선순위/)).toBeInTheDocument();
  });

  it.each(['loading', 'empty', 'error', 'unauthorized'] as const)('%s에서 이전 결과를 노출하지 않는다', (state) => {
    const { rerender } = render(<SkillGapPage status={{ state: 'ready', result: skillGapPreviewResult }} />);
    rerender(<SkillGapPage status={{ state }} />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('백엔드 개발자')).not.toBeInTheDocument();
    expect(screen.getByRole(state === 'error' ? 'alert' : 'status')).toBeInTheDocument();
  });

  it('실패 상태의 재시도를 전달한다', () => {
    const retry = vi.fn();
    render(<SkillGapPage status={{ state: 'error' }} onRetry={retry} />);
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it('오래된 결과를 알리고 재분석 중 중복 요청을 막는다', () => {
    const analyze = vi.fn();
    const status = { state: 'ready' as const, result: { ...skillGapPreviewResult, is_stale: true } };
    const { rerender } = render(<SkillGapPage status={status} onAnalyze={analyze} />);
    expect(screen.getByText(/이전 입력으로/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '재분석' }));
    expect(analyze).toHaveBeenCalledOnce();
    rerender(<SkillGapPage status={status} onAnalyze={analyze} analyzing />);
    fireEvent.click(screen.getByRole('button', { name: '재분석 중…' }));
    expect(analyze).toHaveBeenCalledOnce();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('재분석 실패 시 이전 결과임을 밝히고 새 결과를 받으면 교체한다', () => {
    const { rerender } = render(<SkillGapPage status={{ state: 'ready', result: skillGapPreviewResult }} analysisFailed />);
    expect(screen.getByRole('alert')).toHaveTextContent('이전 결과');
    const result = { ...skillGapPreviewResult, items: skillGapPreviewResult.items.map((item) => ({ ...item, observed_level: item.required_level, gap: 0 })) };
    rerender(<SkillGapPage status={{ state: 'ready', result }} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('0개')).toBeInTheDocument();
    expect(screen.getByText(/모두 충족했습니다/)).toBeInTheDocument();
  });

  it('빈 항목을 모두 충족한 결과로 오인하지 않는다', () => {
    render(<SkillGapPage status={{ state: 'ready', result: { ...skillGapPreviewResult, items: [] } }} />);
    expect(screen.getByText(/모두 충족한다고 판단할 수 없습니다/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('빈 결과에서 분석 요청을 전달한다', () => {
    const analyze = vi.fn();
    render(<SkillGapPage status={{ state: 'empty' }} onAnalyze={analyze} />);
    fireEvent.click(screen.getByRole('button', { name: '분석하기' }));
    expect(analyze).toHaveBeenCalledOnce();
  });

  it('첫 분석 대기 중 버튼과 포커스 위치를 유지하고 중복 요청을 막는다', () => {
    const analyze = vi.fn();
    const { rerender } = render(<SkillGapPage status={{ state: 'empty' }} onAnalyze={analyze} />);
    const button = screen.getByRole('button', { name: '분석하기' });
    button.focus();
    expect(button).toHaveFocus();
    rerender(<SkillGapPage status={{ state: 'empty' }} onAnalyze={analyze} analyzing />);
    expect(screen.getByRole('button', { name: '분석 중…' })).toBe(button);
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(analyze).not.toHaveBeenCalled();
  });

  it('첫 분석 실패를 이전 결과가 있는 것처럼 안내하지 않는다', () => {
    render(<SkillGapPage status={{ state: 'empty' }} analysisFailed />);
    expect(screen.getByRole('alert')).toHaveTextContent('분석에 실패했습니다.');
    expect(screen.getByRole('alert')).not.toHaveTextContent('이전 결과');
  });

  it('인증이 풀리면 남아 있는 분석 상태 안내도 숨긴다', () => {
    render(<SkillGapPage status={{ state: 'unauthorized' }} analyzing analysisFailed />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/새로운 분석 결과/)).not.toBeInTheDocument();
  });

  it('표 스크롤 영역을 키보드로 포커스할 수 있고 제목 셀에 scope가 있다', () => {
    render(<SkillGapPage status={{ state: 'ready', result: skillGapPreviewResult }} />);
    const region = screen.getByRole('region', { name: /목표 직무와 내 기술 비교/ });
    expect(region).toHaveAttribute('tabindex', '0');
    region.focus();
    expect(region).toHaveFocus();
    for (const header of screen.getAllByRole('columnheader')) expect(header).toHaveAttribute('scope', 'col');
  });
});
