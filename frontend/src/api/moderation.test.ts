import { describe, expect, it, vi } from 'vitest';
import {
  MOCK_ADMIN_ID, OTHER_ADMIN_ID, THIRD_ADMIN_ID, createMockModerationService, seedModerationCases,
} from '../mocks/moderation';
import { ApiError } from './errors';
import { availableActions, moderationErrorMessage, rejectInputError, type ModerationCaseDetail } from './moderation';
import { createHttpModerationService } from './moderationHttp';
import type { HttpClient, HttpRequest } from './http';

const seed = (id: string) => seedModerationCases().find((c) => c.case_id === id)!;
const service = (viewer: string | null = MOCK_ADMIN_ID) => createMockModerationService({ viewer: () => viewer });
const rejects = async (promise: Promise<unknown>, status: number, code?: string) => {
  const error = await promise.then(() => null, (e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).status).toBe(status);
  if (code) expect((error as ApiError).code).toBe(code);
};

describe('availableActions (UX only, mirrors T80 guards)', () => {
  const reasonOf = (a: ReturnType<typeof availableActions>['assign']) => (a.allowed ? '' : a.reason);
  it.each([
    ['mc-00001', '', '담당을 시작한 뒤'],
    ['mc-00002', '자기 콘텐츠', '담당을 시작한 뒤'],
    ['mc-00003', '이미 담당자가', ''],
    ['mc-00004', '이미 담당자가', '담당자만'],
    ['mc-00005', '최초 결정자', '담당을 시작한 뒤'],
    ['mc-00006', '', '담당을 시작한 뒤'],
    ['mc-00007', '이미 결정된', '이미 결정된'],
    ['mc-00008', '이미 결정된', '이미 결정된'],
    ['mc-00009', '종료된', '종료된'],
  ])('%s: assign "%s" / decide "%s" ("" = allowed)', (id, assignReason, decideReason) => {
    const actions = availableActions(seed(id), MOCK_ADMIN_ID);
    expect(actions.assign.allowed).toBe(assignReason === '');
    expect(actions.decide.allowed).toBe(decideReason === '');
    expect(reasonOf(actions.assign)).toContain(assignReason);
    expect(reasonOf(actions.decide)).toContain(decideReason);
  });

  it('denies everything without a known viewer', () => {
    expect(availableActions(seed('mc-00001'), undefined).assign.allowed).toBe(false);
  });

  it('validates reject input like the policy (§5.1)', () => {
    expect(rejectInputError('', '')).toMatch(/사유를 선택/);
    expect(rejectInputError('NOT_A_CODE', '')).toMatch(/사유를 선택/);
    expect(rejectInputError('OTHER', '   ')).toMatch(/설명을 입력/);
    expect(rejectInputError('HARMFUL', 'x'.repeat(501))).toMatch(/500자/);
    expect(rejectInputError('OTHER', '설명')).toBeNull();
    expect(rejectInputError('DUPLICATE', '')).toBeNull();
  });

  it.each([
    [new ApiError(403, 'x', undefined, 'FORBIDDEN'), '권한', false],
    [new ApiError(404, 'x', undefined, 'NOT_FOUND'), '찾을 수 없습니다', false],
    [new ApiError(409, 'x', undefined, 'APPROVAL_CLOSED'), '이미 처리', true],
    [new ApiError(409, 'x', undefined, 'CONFLICT'), '먼저', true],
    [new ApiError(422, 'x', undefined, 'VALIDATION_FAILED'), '입력값', false],
    [new ApiError(503, 'x'), '잠시 후', false],
  ])('maps %s', (error, text, reload) => {
    const mapped = moderationErrorMessage(error);
    expect(mapped.message).toContain(text);
    expect(mapped.reload).toBe(reload);
  });
});

describe('mock adapter enforces the rules like a server would', () => {
  it('lists synthetic cases without internal fields, filtered and sorted by priority', async () => {
    const all = await service().list({});
    expect(all.items).toHaveLength(9);
    expect(all.items[0]!.priority).toBe(1);
    for (const item of all.items) {
      expect(Object.keys(item)).not.toEqual(expect.arrayContaining(['content_owner_id', 'events', 'reason_code']));
      expect(item.target_summary).toMatch(/^\[합성\]/);
    }
    expect((await service().list({ status: 'REJECTED' })).items.map((c) => c.case_id)).toEqual(['mc-00008']);
    expect((await service().list({ target_type: 'company' })).items.map((c) => c.case_id)).toEqual(['mc-00006']);
    expect((await service().list({ priority: 1 })).items.map((c) => c.case_id)).toEqual(['mc-00001']);
  });

  it('401 without login, 403 for a non-admin, 404 for an unknown case', async () => {
    expect.hasAssertions();
    await rejects(service(null).list({}), 401, 'UNAUTHENTICATED');
    await rejects(service('user@example.com').list({}), 403, 'FORBIDDEN');
    await rejects(service().get('mc-nope'), 404, 'NOT_FOUND');
  });

  it('assign → approve updates status, version, deciders and history', async () => {
    const s = service();
    const assigned = await s.assign('mc-00001', { version: 1 });
    expect([assigned.status, assigned.assignee_id, assigned.version]).toEqual(['IN_REVIEW', MOCK_ADMIN_ID, 2]);
    const approved = await s.decide('mc-00001', { version: 2, decision: 'APPROVE' });
    expect([approved.status, approved.assignee_id, approved.first_decider_id, approved.version])
      .toEqual(['APPROVED', null, MOCK_ADMIN_ID, 3]);
    expect(approved.events.map((e) => e.event)).toEqual(['SUBMIT', 'ASSIGN', 'APPROVE']);
  });

  it('server-side blocks: self content, other assignee, first decider on appeal, decided case, stale version', async () => {
    expect.hasAssertions();
    const s = service();
    await rejects(s.assign('mc-00002', { version: 1 }), 403, 'FORBIDDEN');
    await rejects(s.decide('mc-00004', { version: 2, decision: 'APPROVE' }), 403, 'FORBIDDEN');
    await rejects(s.assign('mc-00005', { version: 4 }), 403, 'FORBIDDEN');
    await rejects(s.decide('mc-00007', { version: 3, decision: 'APPROVE' }), 409, 'APPROVAL_CLOSED');
    await rejects(s.decide('mc-00009', { version: 2, decision: 'APPROVE' }), 409, 'APPROVAL_CLOSED');
    await rejects(s.decide('mc-00001', { version: 1, decision: 'APPROVE' }), 409, 'CONFLICT');
    await rejects(s.assign('mc-00003', { version: 2 }), 409, 'CONFLICT');
    await rejects(s.assign('mc-00001', { version: 99 }), 409, 'CONFLICT');
  });

  it('another admin can take the appeal review, the first decider cannot', async () => {
    const asOther = createMockModerationService({ viewer: () => THIRD_ADMIN_ID });
    expect((await asOther.assign('mc-00005', { version: 4 })).status).toBe('IN_REVIEW');
    const asFirst = createMockModerationService({ viewer: () => OTHER_ADMIN_ID });
    await rejects(asFirst.assign('mc-00006', { version: 4 }), 403);
  });

  it('release returns an in-review case to PENDING (or APPEALED in the appeal stage), only while IN_REVIEW', async () => {
    const s = service();
    const released = await s.release('mc-00003', { version: 2 });
    expect([released.status, released.assignee_id, released.events.at(-1)!.event]).toEqual(['PENDING', null, 'RELEASE']);
    await rejects(s.release('mc-00003', { version: 3 }), 409, 'CONFLICT');
    await rejects(s.release('mc-00007', { version: 3 }), 409, 'APPROVAL_CLOSED');
    const asThird = createMockModerationService({ viewer: () => THIRD_ADMIN_ID });
    await asThird.assign('mc-00005', { version: 4 });
    const back = await asThird.release('mc-00005', { version: 5 });
    expect([back.status, back.events.at(-1)!.event, back.events.at(-1)!.actor_user_id])
      .toEqual(['APPEALED', 'RELEASE_APPEAL', THIRD_ADMIN_ID]);
  });

  it('reject requires a valid reason and a note for OTHER (422)', async () => {
    const s = service();
    await rejects(s.decide('mc-00003', { version: 2, decision: 'REJECT', reason_code: '' as never }), 422, 'VALIDATION_FAILED');
    await rejects(s.decide('mc-00003', { version: 2, decision: 'REJECT', reason_code: 'OTHER' }), 422);
    await rejects(s.decide('mc-00003', { version: 2, decision: 'REJECT', reason_code: 'HARMFUL', note: 'x'.repeat(501) }), 422);
    const rejected = await s.decide('mc-00003', { version: 2, decision: 'REJECT', reason_code: 'OTHER', note: '합성 설명' });
    expect([rejected.status, rejected.reason_code]).toEqual(['REJECTED', 'OTHER']);
    expect(JSON.stringify(rejected)).not.toContain('합성 설명');
  });

  it('touch() simulates another admin, failNext() injects errors, and results are copies', async () => {
    const s = service();
    s.touch('mc-00003');
    await rejects(s.decide('mc-00003', { version: 2, decision: 'APPROVE' }), 409, 'CONFLICT');
    s.failNext(new ApiError(503, 'x'));
    await rejects(s.list({}), 503);
    const first = await s.get('mc-00001');
    (first as ModerationCaseDetail).status = 'APPROVED';
    expect((await s.get('mc-00001')).status).toBe('PENDING');
  });
});

describe('real API adapter (prepared for T81, not wired)', () => {
  it('targets the proposed T80 contract paths', async () => {
    const request = vi.fn<(path: string, init?: HttpRequest) => Promise<unknown>>(async () => ({}));
    const http = createHttpModerationService({ request: request as unknown as HttpClient['request'] });
    await http.list({ status: 'PENDING' });
    await http.assign('mc 1', { version: 3 });
    await http.decide('mc-1', { version: 3, decision: 'APPROVE' });
    expect(request.mock.calls.map(([path, init]) => [path, init?.method ?? 'GET'])).toEqual([
      ['/v1/admin/moderation-cases', 'GET'],
      ['/v1/admin/moderation-cases/mc%201/assignment', 'POST'],
      ['/v1/admin/moderation-cases/mc-1/decision', 'POST'],
    ]);
  });
});
