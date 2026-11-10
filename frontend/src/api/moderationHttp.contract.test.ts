/// <reference types="node" />
/**
 * T82 HTTP Adapter 독립 계약 테스트 — 실제 HttpClient 로 "어떤 요청이 나가는지"만 고정합니다.
 * 기준은 T80 구현 계약 §4의 **제안** 경로입니다(T81 API·OpenAPI 없음). 서버가 없으므로 fetch 는 가짜이고,
 * 이 테스트 PASS는 실제 API 연동 PASS가 아닙니다. T81 OpenAPI가 나오면 그 계약으로 다시 맞춥니다.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from './errors';
import { CSRF_HEADER, createHttpClient } from './http';
import { moderationErrorMessage } from './moderation';
import { createHttpModerationService } from './moderationHttp';

type Sent = { url: string; method: string; headers: Record<string, string>; body: unknown; signal?: AbortSignal | null };

function setup(response: { status: number; body?: unknown } = { status: 200, body: {} }) {
  const sent: Sent[] = [];
  const fetchSpy = vi.fn<typeof fetch>(async (input, init) => {
    sent.push({ url: String(input), method: init?.method ?? 'GET', headers: init?.headers as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined, signal: init?.signal });
    return new Response(JSON.stringify(response.body ?? {}), { status: response.status,
      headers: { 'Content-Type': 'application/json' } });
  });
  const onUnauthorized = vi.fn<(error: ApiError) => void>();
  const http = createHttpClient({ baseUrl: '/api', fetch: fetchSpy, getToken: () => 'synthetic-token', onUnauthorized });
  return { service: createHttpModerationService(http), sent, onUnauthorized };
}

describe('request shapes against the T80 §4 proposal', () => {
  it('list: GET with only the given filters as query, bearer token attached, no CSRF header on GET', async () => {
    const { service, sent } = setup({ status: 200, body: { items: [], next_cursor: null } });
    await service.list({ status: 'PENDING', target_type: 'company', priority: 1 });
    await service.list({});
    expect(sent[0]!.url).toBe('/api/v1/admin/moderation-cases?status=PENDING&target_type=company&priority=1');
    expect(sent[1]!.url).toBe('/api/v1/admin/moderation-cases');
    expect(sent[0]!.method).toBe('GET');
    expect(sent[0]!.headers.Authorization).toBe('Bearer synthetic-token');
    expect(sent[0]!.headers[CSRF_HEADER]).toBeUndefined();
  });

  it('get: path-encodes the case id', async () => {
    const { service, sent } = setup();
    await service.get('mc/../x 1');
    expect(sent[0]!.url).toBe('/api/v1/admin/moderation-cases/mc%2F..%2Fx%201');
  });

  it('assign: POST {version} only — no assignee or viewer id from the client', async () => {
    const { service, sent } = setup();
    await service.assign('mc-1', { version: 4 });
    expect([sent[0]!.method, sent[0]!.url]).toEqual(['POST', '/api/v1/admin/moderation-cases/mc-1/assignment']);
    expect(sent[0]!.body).toEqual({ version: 4 });
    expect(sent[0]!.headers[CSRF_HEADER]).toBe('1');
    expect(sent[0]!.headers['Content-Type']).toBe('application/json');
  });

  it('decision: approve and reject bodies match {version, decision, reason_code?, note?}', async () => {
    const { service, sent } = setup();
    await service.decide('mc-1', { version: 2, decision: 'APPROVE' });
    await service.decide('mc-1', { version: 2, decision: 'REJECT', reason_code: 'OTHER', note: '합성 설명' });
    expect(sent.map((s) => [s.method, s.url])).toEqual([
      ['POST', '/api/v1/admin/moderation-cases/mc-1/decision'],
      ['POST', '/api/v1/admin/moderation-cases/mc-1/decision'],
    ]);
    expect(sent[0]!.body).toEqual({ version: 2, decision: 'APPROVE' });
    expect(sent[1]!.body).toEqual({ version: 2, decision: 'REJECT', reason_code: 'OTHER', note: '합성 설명' });
    for (const s of sent) expect(Object.keys(s.body as object)).not.toContain('user_id');
  });

  it('read requests pass the AbortSignal (stale responses can be dropped by useQuery)', async () => {
    const { service, sent } = setup();
    const controller = new AbortController();
    await service.list({}, controller.signal);
    await service.get('mc-1', controller.signal);
    expect(sent.every((s) => s.signal === controller.signal)).toBe(true);
  });
});

describe('server errors become ApiError and the UI messages', () => {
  it.each([
    [409, 'CONFLICT', '먼저', true],
    [409, 'APPROVAL_CLOSED', '이미 처리', true],
    [403, 'FORBIDDEN', '권한', false],
    [404, 'NOT_FOUND', '찾을 수 없습니다', false],
    [422, 'VALIDATION_FAILED', '입력값', false],
    [503, 'DEPENDENCY_UNAVAILABLE', '잠시 후', false],
  ])('%i %s', async (status, code, text, reload) => {
    const { service } = setup({ status, body: { code, status, message: 'server text' } });
    const error = await service.decide('mc-1', { version: 1, decision: 'APPROVE' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect([(error as ApiError).status, (error as ApiError).code]).toEqual([status, code]);
    expect(moderationErrorMessage(error)).toEqual(expect.objectContaining({ reload }));
    expect(moderationErrorMessage(error).message).toContain(text);
  });

  it('401 goes through the existing onUnauthorized session handling', async () => {
    const { service, onUnauthorized } = setup({ status: 401, body: { code: 'UNAUTHENTICATED', status: 401 } });
    await expect(service.list({})).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe('T81 not ready: the HTTP adapter is not wired', () => {
  it('the provider only creates the in-memory mock adapter', () => {
    const provider = readFileSync(resolve(cwd(), 'src/admin/ModerationServiceProvider.tsx'), 'utf8');
    expect(provider).toContain('createMockModerationService');
    expect(provider).not.toMatch(/import[^;]*createHttpModerationService/);
  });

  it('the feature flag still requires mock mode', () => {
    const env = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    expect(env).toContain("adminModerationUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_ADMIN_MODERATION_UI === 'true'");
  });
});
