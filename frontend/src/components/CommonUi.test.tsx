import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StatePanel } from './StatePanel';
import { TextField } from './TextField';
import { DataTable } from './DataTable';
import { FormPreview } from '../pages/FormPreview';

describe('T20 공통 UI', () => {
  it('오류 상태에서 다시 시도 동작을 실행한다', () => {
    const onRetry = vi.fn();

    render(
      <StatePanel
        variant="error"
        actionLabel="다시 시도"
        onAction={onRetry}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('입력란에 라벨·도움말·오류를 연결한다', () => {
    render(
      <TextField
        label="이메일"
        hint="연락받을 주소"
        error="이메일 형식을 확인해 주세요."
        required
      />,
    );

    const input = screen.getByRole('textbox', { name: /이메일/ });

    expect(input).toBeRequired();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription(
      '연락받을 주소 이메일 형식을 확인해 주세요.',
    );
  });

  it('데이터가 없으면 표 대신 빈 상태를 표시한다', () => {
    render(
      <DataTable
        caption="목록"
        columns={[
          {
            key: 'name',
            header: '이름',
            render: (row: { id: string; name: string }) => row.name,
          },
        ]}
        rows={[]}
        getRowKey={(row) => row.id}
      />,
    );

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('목록: 데이터가 없습니다')).toBeInTheDocument();
  });

  it('빈 폼 제출 시 오류를 표시하고 첫 입력란으로 포커스를 옮긴다', () => {
    render(<FormPreview />);

    fireEvent.click(screen.getByRole('button', { name: '입력 확인' }));

    expect(screen.getByText('표시 이름을 입력해 주세요.')).toBeInTheDocument();
    expect(screen.getByText('이메일을 입력해 주세요.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /표시 이름/ })).toHaveFocus();
  });

  it('올바른 입력값이면 검증 통과를 안내한다', () => {
    render(<FormPreview />);

    fireEvent.change(screen.getByRole('textbox', { name: /표시 이름/ }), {
      target: { value: '테스트 사용자' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: /이메일/ }), {
      target: { value: 'test@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: '입력 확인' }));

    expect(
      screen.getByText(
        '입력 검증을 통과했습니다. 실제 서버에 저장되지는 않습니다.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('이메일을 입력해 주세요.')).not.toBeInTheDocument();
  });
});
