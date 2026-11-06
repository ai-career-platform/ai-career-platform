import { fireEvent, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { routes } from '../routes';
import { Button } from '../components/Button';

function renderHome() {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/'] })} />);
}

describe('메인 페이지와 공통 컴포넌트', () => {
  it('홈에서 랜딩과 상단 메뉴를 표시하고 시스템 상태 화면은 표시하지 않는다', () => {
    renderHome();
    expect(screen.getByRole('heading', { level: 1, name: /더 나다운 일/ })).toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: '주 메뉴' })).getByRole('link', { name: '채용 탐색' })).toHaveAttribute('href', '#positions');
    expect(screen.queryByTestId('backend-status')).not.toBeInTheDocument();
    expect(screen.getByText('4개의 예시 포지션')).toBeInTheDocument();
  });

  it('직무와 검색 조건을 함께 적용하고 빈 결과에서 초기화한다', () => {
    renderHome();
    fireEvent.click(screen.getByRole('button', { name: '개발' }));
    expect(screen.getByRole('button', { name: '개발' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('1개의 예시 포지션')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '프론트엔드 개발자' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '데이터 분석가' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '없는 공고' } });
    expect(screen.getByText('조건에 맞는 예시 공고가 없어요.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검색 조건 초기화' }));
    expect(screen.getByRole('searchbox')).toHaveValue('');
    expect(screen.getByText('4개의 예시 포지션')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'python' } });
    expect(screen.getByText('1개의 예시 포지션')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '데이터 분석가' })).toBeInTheDocument();
  });

  it('AI 기능 버튼은 준비 중 안내를 표시한다', () => {
    renderHome();
    fireEvent.click(screen.getByRole('button', { name: /AI 커리어 분석 안내/ }));
    expect(screen.getByText('AI 커리어 분석은 현재 준비 중입니다.')).toBeInTheDocument();
  });

  it('공통 버튼은 기본적으로 폼 제출을 하지 않고 비활성 상태를 지킨다', () => {
    const onClick = vi.fn();
    const onSubmit = vi.fn((event) => event.preventDefault());
    render(<form onSubmit={onSubmit}><Button onClick={onClick}>동작</Button><Button disabled onClick={onClick}>차단</Button></form>);
    fireEvent.click(screen.getByRole('button', { name: '동작' }));
    fireEvent.click(screen.getByRole('button', { name: '차단' }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
