import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { routes } from './routes';

const renderAt = (path: string) =>
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);

const mockFetch = (responses: Record<string, { status: number; body: unknown }>) =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const entry = responses[url] ?? { status: 404, body: {} };
      return new Response(JSON.stringify(entry.body), { status: entry.status });
    }),
  );

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('routing and home page', () => {
  it('shows Operational when all health APIs succeed', async () => {
    mockFetch({
      '/api/health': { status: 200, body: { status: 'ok', service: 'ai-career-backend' } },
      '/api/version': { status: 200, body: { application: 'x', environment: 'test', version: '0.1.0' } },
      '/api/health/db': { status: 200, body: { status: 'ok', service: 'ai-career-database' } },
    });

    renderAt('/system-status');

    expect(screen.getByRole('heading', { name: 'AI Career Platform', level: 1 })).toBeInTheDocument();
    expect(await screen.findByText('Operational')).toBeInTheDocument();
    expect(screen.getByTestId('backend-status')).toHaveTextContent('Connected');
    expect(screen.getByTestId('backend-version')).toHaveTextContent('0.1.0');
  });

  it('shows Degraded when the DB health API returns 503', async () => {
    mockFetch({
      '/api/health': { status: 200, body: { status: 'ok', service: 'ai-career-backend' } },
      '/api/version': { status: 200, body: { application: 'x', environment: 'test', version: '0.1.0' } },
      '/api/health/db': { status: 503, body: { status: 'error' } },
    });

    renderAt('/system-status');

    expect(await screen.findByText('Degraded')).toBeInTheDocument();
    expect(screen.getByTestId('backend-status')).toHaveTextContent('Connected');
  });

  it('renders the not-found page for unknown routes', () => {
    mockFetch({});

    renderAt('/unknown-page');

    expect(screen.getByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '홈으로 이동' })).toHaveAttribute('href', '/');
  });
});
