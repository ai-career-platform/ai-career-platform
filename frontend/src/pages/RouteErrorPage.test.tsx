/**
 * E2E-006 D-1 — 렌더링 중 예외가 나도 React Router 기본 오류 화면(스택트레이스)이 아니라
 * RouteErrorPage 가 보이고, 화면 오류면 상단·메뉴(AppLayout)가 남는지 실제 buildRoutes 로 확인합니다.
 */
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { buildRoutes } from '../routes';

const failure = vi.hoisted(() => ({ page: null as unknown, layout: false }));

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false } }));
vi.mock('./JobExplorerPage', () => ({
  JobExplorerPage: () => {
    if (failure.page) throw failure.page;
    return <h1>직무 화면</h1>;
  },
}));
vi.mock('../layouts/AppLayout', async (importOriginal) => {
  const original = await importOriginal<typeof import('../layouts/AppLayout')>();
  return {
    AppLayout: (props: Parameters<typeof original.AppLayout>[0]) => {
      if (failure.layout) throw new Error('layout-secret-detail at AppLayout.tsx:1');
      return <original.AppLayout {...props} />;
    },
  };
});

const open = (path: string) => render(<RouterProvider router={createMemoryRouter(buildRoutes({ adminModerationUi: false }), { initialEntries: [path] })} />);

beforeEach(() => {
  failure.page = null; failure.layout = false;
  vi.spyOn(console, 'error').mockImplementation(() => {}); // React·Router 의 개발용 오류 로그는 화면 검증과 무관
});
afterEach(() => { vi.restoreAllMocks(); });

describe('route error boundary (E2E-006 D-1)', () => {
  it('renders the page normally when nothing throws', async () => {
    open('/job-roles');
    expect(await screen.findByRole('heading', { name: '직무 화면' })).toBeInTheDocument();
  });

  it('keeps the app layout and shows a generic error without the message or stack when a page throws', async () => {
    failure.page = new TypeError("Cannot read properties of undefined (reading 'items') at secret.js:9:213302");
    open('/job-roles');
    expect(await screen.findByText('화면을 표시하지 못했습니다')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: '주 메뉴' })).toBeInTheDocument();   // 레이아웃 유지
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '홈으로 이동' })).toHaveAttribute('href', '/');
    expect(document.body).not.toHaveTextContent(/Unexpected Application Error|secret\.js|reading 'items'|TypeError/);
    expect(screen.queryByText(/문의용 요청 번호/)).not.toBeInTheDocument();       // ApiError 가 아니면 번호 없음
  });

  it('shows the request id when the thrown error is an ApiError carrying one', async () => {
    failure.page = new ApiError(502, '/v1/job-roles', 'raw-internal-message', 'BAD_GATEWAY', undefined, 'req-0123456789abcdef');
    open('/job-roles');
    expect(await screen.findByText('req-0123456789abcdef')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('raw-internal-message');
  });

  it('falls back to the root boundary when the layout itself throws', async () => {
    failure.layout = true;
    open('/job-roles');
    expect(await screen.findByText('화면을 표시하지 못했습니다')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/layout-secret-detail|AppLayout\.tsx|Unexpected Application Error/);
  });
});
