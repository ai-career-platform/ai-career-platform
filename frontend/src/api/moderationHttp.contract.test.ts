/// <reference types="node" />
/**
 * T82 HTTP Adapter 계약 테스트 — 실제 HttpClient 로 "어떤 요청이 나가는지"를 고정하고, T81 백엔드 계약 스냅샷
 * (docs/admin/t81_moderation_api.snapshot.json, 라우터와 같음은 backend 시험이 확인)과 경로·필드·enum 이 맞는지
 * 확인합니다. 백엔드 소스는 읽지 않습니다(이미지 빌드에는 frontend/ 와 docs 만 있음). fetch 는 가짜이므로
 * 이 테스트 PASS는 실제 서버 연동 PASS가 아닙니다(실제 DB 시험: backend/tests/test_t81_moderation_postgres.py).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from './errors';
import { CSRF_HEADER, createHttpClient } from './http';
import {
  MODERATION_STATUSES, REASON_CODES, TARGET_TYPES, moderationErrorMessage,
  type ModerationCaseDetail, type ModerationCaseEvent,
} from './moderation';
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

describe('T81 wiring: mock only in mock mode, otherwise the real API (flag still default off)', () => {
  it('the provider picks the mock adapter only when env.mockEnabled, else api.moderation', () => {
    const provider = readFileSync(resolve(cwd(), 'src/admin/ModerationServiceProvider.tsx'), 'utf8');
    expect(provider).toContain('env.mockEnabled ? createMockModerationService');
    expect(provider).toContain(': api.moderation');
    const index = readFileSync(resolve(cwd(), 'src/api/index.ts'), 'utf8');
    expect(index).toContain('moderation: createHttpModerationService(http)');
  });

  it('the feature flag is its own switch and is off unless set to "true"', () => {
    const env = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    expect(env).toContain("adminModerationUi: import.meta.env.VITE_ADMIN_MODERATION_UI === 'true'");
  });
});

describe('T81 backend contract (docs/admin/t81_moderation_api.snapshot.json)', () => {
  it('release: POST {version} to /assignment/release', async () => {
    const { service, sent } = setup();
    await service.release('mc-1', { version: 3 });
    expect([sent[0]!.method, sent[0]!.url, sent[0]!.body]).toEqual(
      ['POST', '/api/v1/admin/moderation-cases/mc-1/assignment/release', { version: 3 }]);
    expect(sent[0]!.headers[CSRF_HEADER]).toBe('1');
  });

  it('list passes limit and cursor as query and returns next_cursor', async () => {
    const { service, sent } = setup({ status: 200, body: { items: [], next_cursor: 'c2' } });
    const page = await service.list({ status: 'IN_REVIEW', limit: 100 });
    expect(sent[0]!.url).toBe('/api/v1/admin/moderation-cases?status=IN_REVIEW&limit=100');
    expect(page.next_cursor).toBe('c2');
  });

  it('every path, method, request field and enum used by the UI exists in the backend contract snapshot', () => {
    // docs/admin/t81_moderation_api.snapshot.json 은 backend/tests/test_t81_moderation_contract_snapshot.py 가
    // 실제 라우터 OpenAPI 와 같음을 확인한다(이미지 빌드에는 backend/ 가 없고 docs 만 있음).
    type Field = { required?: boolean; enum?: string[] };
    type Op = { query: Record<string, Field>; body?: Record<string, Field>; response: Record<string, Field> };
    const snapshot = JSON.parse(readFileSync(resolve(cwd(), '../docs/admin/t81_moderation_api.snapshot.json'), 'utf8')) as {
      paths: Record<string, Op>; schemas: Record<string, Record<string, Field>>;
    };
    const base = 'POST /v1/admin/moderation-cases/{case_id}';
    expect(Object.keys(snapshot.paths).sort()).toEqual([
      'GET /v1/admin/moderation-cases', 'GET /v1/admin/moderation-cases/{case_id}', `${base}/assignment`,
      `${base}/assignment/release`, `${base}/decision`,
    ]);
    const list = snapshot.paths['GET /v1/admin/moderation-cases']!;
    expect(Object.keys(list.query)).toEqual(expect.arrayContaining(['status', 'target_type', 'priority', 'limit', 'cursor']));
    expect(list.query.status!.enum).toEqual([...MODERATION_STATUSES]);
    expect(list.query.target_type!.enum).toEqual([...TARGET_TYPES]);
    expect(Object.keys(list.response).sort()).toEqual(['items', 'next_cursor']);
    for (const path of [`${base}/assignment`, `${base}/assignment/release`]) {
      expect(snapshot.paths[path]!.body).toEqual({ version: { required: true } });
    }
    const decision = snapshot.paths[`${base}/decision`]!.body!;
    expect(Object.keys(decision).sort()).toEqual(['decision', 'note', 'reason_code', 'version']);
    expect(decision.decision!.enum).toEqual(['APPROVE', 'REJECT']);
    expect(decision.reason_code!.enum).toEqual([...REASON_CODES]);
    // 화면이 읽는 응답 필드는 모두 서버 응답에 있다
    const detail = snapshot.paths['GET /v1/admin/moderation-cases/{case_id}']!.response;
    const uiDetail: (keyof ModerationCaseDetail)[] = ['case_id', 'target_type', 'target_id', 'target_summary', 'trigger',
      'status', 'priority', 'assignee_id', 'due_at', 'flags', 'report_count', 'version', 'content_owner_id', 'submitted_by',
      'first_decider_id', 'decided_by', 'decided_at', 'reason_code', 'appeal_count', 'close_reason', 'created_at', 'events'];
    expect(Object.keys(detail)).toEqual(expect.arrayContaining(uiDetail));
    const uiEvent: (keyof ModerationCaseEvent)[] = ['event_id', 'event', 'from_status', 'to_status', 'actor_user_id',
      'reason_code', 'occurred_at'];
    expect(Object.keys(snapshot.schemas.CaseEventOut!).sort()).toEqual([...uiEvent].sort());
  });

  it('503 (no content effect / DB) tells the admin nothing changed', () => {
    const mapped = moderationErrorMessage(new ApiError(503, 'x', undefined, 'DEPENDENCY_UNAVAILABLE'));
    expect(mapped.message).toContain('아무것도 바뀌지 않았습니다');
    expect(moderationErrorMessage(new ApiError(400, 'x', undefined, 'INVALID_CURSOR')).reload).toBe(true);
  });
});
