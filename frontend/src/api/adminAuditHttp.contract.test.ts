/**
 * T85 HTTP Adapter ↔ T84 **확정 계약** 정합성 (실제 createHttpClient + 가짜 fetch).
 * 실제 서버에 연결하지 않습니다. 계약 기준은 docs/api/openapi.yaml 과 생성 타입(schema.gen.ts)입니다.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { describe, expect, it, vi } from 'vitest';
import { createMockAdminAuditService } from '../mocks/adminAudit';
import {
  GROUP_BY_LABELS, adminAuditErrorMessage, parseCostStatus, type AiUsageBucket, type AuditEvent,
} from './adminAudit';
import { createHttpAdminAuditService } from './adminAuditHttp';
import { ApiError } from './errors';
import { createHttpClient } from './http';

// Windows 체크아웃은 CRLF 일 수 있어 줄바꿈을 맞춥니다.
const SPEC = readFileSync(resolve(cwd(), '../docs/api/openapi.yaml'), 'utf8').replace(/\r\n/g, '\n');
const block = (start: string) => SPEC.slice(SPEC.indexOf(start), SPEC.indexOf('\n  /', SPEC.indexOf(start) + start.length));
const schemaRequired = (name: string) => {
  const at = SPEC.indexOf(`\n    ${name}:\n`);
  const required = SPEC.slice(at).match(/required: \[([^\]]+)\]/)![1]!;
  return required.split(',').map((s) => s.trim()).sort();
};

// T84 백엔드 테스트가 검증한 응답 모양 그대로 (합성 값).
const backendEvent = {
  audit_event_id: '00000000-0000-4000-9000-000000000001', actor_user_id: null, action_code: 'system.behavior.purge',
  resource_type: 'behavior_purge_run', resource_id: '00000000-0000-4000-9000-000000000050', request_id: 'req-t84-0002',
  occurred_at: '2026-11-10T02:00:00.123456Z',
} satisfies AuditEvent;
const backendBucket = { key: '2026-11-02', input_tokens: 3, output_tokens: 3, estimated_cost_usd: 0.300001, request_count: 3 } satisfies AiUsageBucket;

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

function setup(response: () => Response, onUnauthorized = vi.fn<(error: ApiError) => void>()) {
  const fetchSpy = vi.fn<typeof fetch>(async () => response());
  const http = createHttpClient({ baseUrl: '/api', fetch: fetchSpy, getToken: () => 'synthetic-token', onUnauthorized });
  return { service: createHttpAdminAuditService(http), fetchSpy, onUnauthorized };
}
const url = (spy: ReturnType<typeof vi.fn<typeof fetch>>) => new URL(String(spy.mock.calls[0]![0]), 'https://x.invalid');
const headersOf = (spy: ReturnType<typeof vi.fn<typeof fetch>>) => spy.mock.calls[0]![1]!.headers as Record<string, string>;

describe('openapi.yaml (confirmed contract) still matches what the adapter assumes', () => {
  it('both operations exist with the expected query parameters', () => {
    const audit = block('  /admin/audit-events:');
    for (const name of ['from', 'to', 'actor_user_id', 'action_code']) expect(audit).toContain(`name: ${name}`);
    expect(audit).toContain('#/components/parameters/Cursor');
    expect(audit).toContain('AuditEventPage');
    const usage = block('  /admin/ai-usage:');
    expect(usage).toContain('enum: [day, feature_code, provider_model]');
    expect(Object.keys(GROUP_BY_LABELS).sort()).toEqual(['day', 'feature_code', 'provider_model']);
    expect(usage).toContain('AiUsageBucket');
  });

  it('response fields are exactly the contract fields (backend sample and mock adapter)', async () => {
    const eventFields = schemaRequired('AuditEvent');
    const bucketFields = schemaRequired('AiUsageBucket');
    expect(Object.keys(backendEvent).sort()).toEqual(eventFields);
    expect(Object.keys(backendBucket).sort()).toEqual(bucketFields);
    const mock = createMockAdminAuditService({ now: () => new Date('2026-11-10T03:00:00Z') });
    const page = await mock.listEvents({ from: '2026-11-01T00:00:00+09:00', to: '2026-11-11T00:00:00Z' });
    expect(Object.keys(page).sort()).toEqual(['items', 'next_cursor']);
    for (const item of page.items) expect(Object.keys(item).sort()).toEqual(eventFields);
    const usage = await mock.getUsage({ from: '2026-11-01', to: '2026-11-10', group_by: 'day' });
    for (const b of usage.buckets) expect(Object.keys(b).sort()).toEqual(bucketFields);
  });
});

describe('HTTP adapter', () => {
  it('audit list: one /api prefix, contract query only, Bearer, no CSRF on GET, abort signal', async () => {
    const { service, fetchSpy } = setup(() => json({ items: [backendEvent], next_cursor: 'opaque' }));
    const controller = new AbortController();
    const page = await service.listEvents({ from: '2026-11-01T00:00:00+09:00', to: '2026-11-11T00:00:00Z',
      action_code: 'admin.role.grant', limit: 20, cursor: 'abc' }, controller.signal);
    const sent = url(fetchSpy);
    expect(sent.pathname).toBe('/api/v1/admin/audit-events');
    expect([...sent.searchParams.keys()].sort()).toEqual(['action_code', 'cursor', 'from', 'limit', 'to']);
    expect(sent.searchParams.has('actor_user_id')).toBe(false);
    expect(headersOf(fetchSpy).Authorization).toBe('Bearer synthetic-token');
    expect(headersOf(fetchSpy)['X-CSRF-TOKEN']).toBeUndefined();
    expect(fetchSpy.mock.calls[0]![1]!.signal).toBe(controller.signal);
    expect(page).toEqual({ items: [backendEvent], next_cursor: 'opaque' });
  });

  it('empty optional filters are not sent', async () => {
    const { service, fetchSpy } = setup(() => json({ items: [], next_cursor: null }));
    await service.listEvents({ from: 'a+09:00', to: 'b+09:00' });
    expect([...url(fetchSpy).searchParams.keys()].sort()).toEqual(['from', 'to']);
  });

  it.each([
    ['unverified', 'unverified'], [undefined, 'unknown'], ['verified', 'unknown'], ['UNVERIFIED', 'unknown'],
  ] as const)('usage: X-AI-Cost-Status %s → %s (never "verified")', async (header, expected) => {
    const { service, fetchSpy } = setup(() => json([backendBucket], 200, header ? { 'X-AI-Cost-Status': header } : {}));
    const result = await service.getUsage({ from: '2026-11-01', to: '2026-11-07', group_by: 'feature_code' });
    expect(url(fetchSpy).pathname).toBe('/api/v1/admin/ai-usage');
    expect(Object.fromEntries(url(fetchSpy).searchParams)).toEqual({ from: '2026-11-01', to: '2026-11-07', group_by: 'feature_code' });
    expect(result).toEqual({ buckets: [backendBucket], costStatus: expected, source: 'api' });
  });

  it('parseCostStatus only accepts the exact server value', () => {
    expect(parseCostStatus('unverified')).toBe('unverified');
    for (const value of [null, undefined, '', 'verified', ' unverified']) expect(parseCostStatus(value)).toBe('unknown');
  });

  it.each([
    [400, 'INVALID_CURSOR', { resetCursor: true, retry: false }],
    [403, 'FORBIDDEN', { resetCursor: false, retry: false, forbidden: true }],
    [422, 'VALIDATION_FAILED', { resetCursor: false, retry: false }],
    [503, 'DEPENDENCY_UNAVAILABLE', { resetCursor: false, retry: true }],
  ])('server %i %s → ApiError → screen action', async (status, code, view) => {
    const { service } = setup(() => json({ code, status, message: 'server message' }, status));
    const error = await service.listEvents({ from: 'a+09:00', to: 'b+09:00' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe(code);
    expect(adminAuditErrorMessage(error)).toMatchObject(view);
    expect(adminAuditErrorMessage(error).message).not.toContain('server message');
  });

  it('401 calls the existing session handler and error responses do not read headers', async () => {
    const onUnauthorized = vi.fn<(error: ApiError) => void>();
    const { service } = setup(() => json({ code: 'TOKEN_EXPIRED', status: 401, message: 'x' }, 401, { 'X-AI-Cost-Status': 'unverified' }), onUnauthorized);
    await expect(service.getUsage({ from: '2026-11-01', to: '2026-11-07', group_by: 'day' })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe('HttpClient onResponseHeaders (T85 extension)', () => {
  it('is called once on success and never on error', async () => {
    const seen = vi.fn<(headers: Headers) => void>();
    const ok = createHttpClient({ baseUrl: '/api', fetch: vi.fn<typeof fetch>(async () => json({}, 200, { 'X-Test': '1' })) });
    await ok.request('/x', { onResponseHeaders: seen });
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen.mock.calls[0]![0].get('X-Test')).toBe('1');
    const bad = createHttpClient({ baseUrl: '/api', fetch: vi.fn<typeof fetch>(async () => json({}, 500)) });
    await bad.request('/x', { onResponseHeaders: seen }).catch(() => undefined);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
