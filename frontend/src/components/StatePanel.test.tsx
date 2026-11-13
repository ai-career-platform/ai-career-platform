import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StatePanel } from './StatePanel';

describe('StatePanel request id (E2E-006 D-2)', () => {
  it('shows the request id on an error panel, separate from the message, next to the retry action', () => {
    const onAction = vi.fn<() => void>();
    render(<StatePanel variant="error" title="목록을 불러오지 못했습니다" description="다시 시도해 주세요."
      actionLabel="다시 시도" onAction={onAction} requestId="req-0123456789abcdef" />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('문의용 요청 번호: req-0123456789abcdef');
    expect(screen.getByText('req-0123456789abcdef').tagName).toBe('CODE');
    // 요청 번호는 제목·설명 문장에 섞이지 않습니다.
    expect(screen.getByText('목록을 불러오지 못했습니다')).not.toHaveTextContent('req-');
    expect(screen.getByText('다시 시도해 주세요.')).not.toHaveTextContent('req-');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('renders no request-id line when there is no id', () => {
    const { container } = render(<StatePanel variant="error" title="실패" actionLabel="다시 시도" onAction={() => {}} />);
    expect(screen.queryByText(/문의용 요청 번호/)).not.toBeInTheDocument();
    expect(container.querySelector('.state-panel-request-id')).toBeNull();
  });

  it('does not show a request id on non-error panels', () => {
    render(<StatePanel variant="empty" title="없음" requestId="req-0123456789abcdef" />);
    expect(screen.queryByText(/문의용 요청 번호/)).not.toBeInTheDocument();
  });
});
