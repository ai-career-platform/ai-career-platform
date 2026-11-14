/**
 * T85 Provider 데이터 경로: Mock 모드면 메모리 Adapter, 아니면 로그인 세션의 API(useApi().adminAudit).
 * 실제 서버에 연결하지 않습니다(가짜 전송).
 */
import { render, screen, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminAuditService } from '../api/adminAudit';
import { spyRequest } from '../test/api';
import { WithApi } from '../test/WithApi';
import { AdminAuditServiceProvider } from './AdminAuditServiceProvider';
import { useAdminAuditService } from './adminAuditContext';

const flags = vi.hoisted(() => ({ mockEnabled: false }));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', get mockEnabled() { return flags.mockEnabled; } } }));

afterEach(() => { flags.mockEnabled = false; });

function Probe() {
  const service = useAdminAuditService();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    void service.listEvents({ from: '2026-11-01T00:00:00+09:00', to: '2026-11-08T00:00:00+09:00', limit: 20 })
      .then((page) => setCount(page.items.length));
  }, [service]);
  return <p>source={service.source ?? 'mock'} count={count ?? '-'}</p>;
}

const page = { items: [], next_cursor: null };

describe('AdminAuditServiceProvider', () => {
  it('real mode: uses the session API client (GET /v1/admin/audit-events with contract query)', async () => {
    const request = spyRequest(async () => page);
    render(<WithApi request={request}><AdminAuditServiceProvider><Probe /></AdminAuditServiceProvider></WithApi>);
    expect(await screen.findByText('source=api count=0')).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(1);
    const [path] = request.mock.calls[0]!;
    const sent = new URL(path, 'https://x.invalid');
    expect(sent.pathname).toBe('/v1/admin/audit-events');
    expect(Object.fromEntries(sent.searchParams)).toEqual({
      from: '2026-11-01T00:00:00+09:00', to: '2026-11-08T00:00:00+09:00', limit: '20',
    });
  });

  it('mock mode: uses the in-memory adapter and sends no request', async () => {
    flags.mockEnabled = true;
    const request = spyRequest(async () => page);
    render(<WithApi request={request}><AdminAuditServiceProvider><Probe /></AdminAuditServiceProvider></WithApi>);
    await waitFor(() => expect(screen.getByText(/^source=mock count=\d+$/)).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.queryByText('source=mock count=-')).not.toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });

  it('the service prop overrides both (tests)', async () => {
    const request = spyRequest(async () => page);
    const service: AdminAuditService = {
      source: 'api',
      listEvents: vi.fn<AdminAuditService['listEvents']>(async () => ({ items: [], next_cursor: null })),
      getUsage: vi.fn<AdminAuditService['getUsage']>(),
    };
    render(<WithApi request={request}><AdminAuditServiceProvider service={service}><Probe /></AdminAuditServiceProvider></WithApi>);
    expect(await screen.findByText('source=api count=0')).toBeInTheDocument();
    expect(service.listEvents).toHaveBeenCalledTimes(1);
    expect(request).not.toHaveBeenCalled();
  });
});
