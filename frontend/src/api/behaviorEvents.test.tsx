import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { env } from '../config/env';
import {
  behaviorEventsApi, behaviorTrackingGranted, createBehaviorTracker, isAllowedMetadata,
  type BehaviorEventInput, type BehaviorTracker,
} from './behaviorEvents';
import { createHttpClient } from './http';
import type { Consent } from './me';

const EVENT_ID = '3ad04800-5d47-47b4-a144-270e7e2e5f5c';
const NOW = new Date('2026-11-10T03:00:00Z');

/** 실제 HttpClient + 가짜 fetch. 응답을 순서대로 돌려주고 보낸 요청을 기록합니다. */
function setup(responses: Array<{ status: number; body?: unknown } | Error>, opts: { enabled?: boolean; consent?: boolean } = {}) {
  const queue = [...responses];
  const fetchSpy = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? { status: 201, body: { event_id: EVENT_ID, status: 'recorded' } };
    if (next instanceof Error) throw next;
    return new Response(JSON.stringify(next.body ?? { code: 'X', status: next.status, message: 'x' }), {
      status: next.status, headers: { 'Content-Type': 'application/json' },
    });
  });
  const onUnauthorized = vi.fn<() => void>();
  const http = createHttpClient({ baseUrl: '/api', fetch: fetchSpy as unknown as typeof fetch, getToken: () => 'token', onUnauthorized });
  const state = { consent: opts.consent ?? true };
  const tracker = createBehaviorTracker({
    enabled: opts.enabled ?? true, hasConsent: () => state.consent, send: behaviorEventsApi(http).record,
    newEventId: () => EVENT_ID, now: () => NOW,
  });
  const sentBodies = () => fetchSpy.mock.calls.map(([, init]) => JSON.parse(String(init?.body)) as BehaviorEventInput);
  return { tracker, fetchSpy, state, onUnauthorized, sentBodies };
}

describe('consent gate', () => {
  it('sends one approved event with consent, using the existing authenticated client', async () => {
    const { tracker, fetchSpy, sentBodies } = setup([{ status: 201, body: { event_id: EVENT_ID, status: 'recorded' } }]);
    await expect(tracker.track('posting.view', { job_posting_id: 'jp_1', list_position: 2 })).resolves.toBe('recorded');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe('/api/v1/me/behavior-events');
    expect(init?.method).toBe('POST');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer token');
    expect(sentBodies()).toEqual([{ event_id: EVENT_ID, event_code: 'posting.view', event_at: '2026-11-10T03:00:00.000Z',
      metadata: { job_posting_id: 'jp_1', list_position: 2 } }]);
    expect(Object.keys(sentBodies()[0]!)).not.toContain('user_id');
  });

  it('sends nothing without consent', async () => {
    const { tracker, fetchSpy } = setup([], { consent: false });
    await expect(tracker.track('page.view', { page_id: 'home' })).resolves.toBe('skipped_no_consent');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('stops immediately after withdrawal (revoke or consent state false)', async () => {
    const { tracker, fetchSpy, state } = setup([]);
    await tracker.track('page.view');
    tracker.revoke();
    await expect(tracker.track('page.view')).resolves.toBe('skipped_no_consent');
    tracker.resume();
    state.consent = false;
    await expect(tracker.track('page.view')).resolves.toBe('skipped_no_consent');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('stops after the server says blocked_no_consent (server is the source of truth)', async () => {
    const { tracker, fetchSpy } = setup([{ status: 200, body: { event_id: EVENT_ID, status: 'blocked_no_consent' } }]);
    await expect(tracker.track('page.view')).resolves.toBe('blocked_no_consent');
    await expect(tracker.track('page.view')).resolves.toBe('skipped_no_consent');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('is disabled by default and sends nothing while disabled', async () => {
    expect(env.behaviorTrackingEnabled).toBe(false);
    const { tracker, fetchSpy } = setup([], { enabled: false });
    await expect(tracker.track('page.view')).resolves.toBe('skipped_disabled');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('reads the latest behavior_tracking consent from the existing consent history', () => {
    const c = (granted: boolean, at: string, code = 'behavior_tracking'): Consent => ({
      consent_id: at, is_required: false, policy_code: code, policy_version: 'v1', granted, recorded_at: at,
    });
    expect(behaviorTrackingGranted([])).toBe(false);
    expect(behaviorTrackingGranted([c(true, '2026-11-01T00:00:00Z'), c(false, '2026-11-02T00:00:00Z')])).toBe(false);
    expect(behaviorTrackingGranted([c(false, '2026-11-01T00:00:00Z'), c(true, '2026-11-02T00:00:00Z')])).toBe(true);
    expect(behaviorTrackingGranted([c(true, '2026-11-02T00:00:00Z', 'llm_processing')])).toBe(false);
  });
});

describe('allowed events and payload', () => {
  it.each([
    ['posting.bookmark', { job_posting_id: 'jp_1' }],
    ['recommendation.click', { recommendation_id: 'r1', rank: 1 }],
    ['recommendation.dismiss', { recommendation_id: 'r1', reason_code: 'x' }],
    ['page.scroll', {}],
  ])('never sends unapproved event %s', async (code, metadata) => {
    const { tracker, fetchSpy } = setup([]);
    const event = { event_id: EVENT_ID, event_code: code, event_at: NOW.toISOString(), metadata } as BehaviorEventInput;
    await expect(tracker.send(event)).resolves.toBe('skipped_not_allowed');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each([
    [{ search_type: 'python backend' }], [{ query: 'python' }], [{ search_type: { nested: 1 } }],
    [{ search_type: ['a'] }], [{ filter_count: Number.NaN }],
  ])('drops search text, unknown keys and nested values: %j', async (metadata) => {
    const { tracker, fetchSpy } = setup([]);
    expect(isAllowedMetadata('search.submit', metadata)).toBe(false);
    await expect(tracker.track('search.submit', metadata as never)).resolves.toBe('skipped_not_allowed');
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('retries and errors never break the screen', () => {
  it('retries a 503 with the same event_id', async () => {
    const { tracker, fetchSpy, sentBodies } = setup([{ status: 503 }, { status: 201, body: { event_id: EVENT_ID, status: 'recorded' } }]);
    await expect(tracker.track('role.view', { job_role_id: 'BACKEND' })).resolves.toBe('recorded');
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(sentBodies().map((b) => b.event_id)).toEqual([EVENT_ID, EVENT_ID]);
  });

  it('resend of the same event reuses its event_id (server answers duplicate)', async () => {
    const { tracker, sentBodies } = setup([
      { status: 201, body: { event_id: EVENT_ID, status: 'recorded' } },
      { status: 200, body: { event_id: EVENT_ID, status: 'duplicate' } },
    ]);
    const event: BehaviorEventInput = { event_id: EVENT_ID, event_code: 'page.view', event_at: NOW.toISOString(), metadata: null };
    expect([await tracker.send(event), await tracker.send(event)]).toEqual(['recorded', 'duplicate']);
    expect(new Set(sentBodies().map((b) => b.event_id))).toEqual(new Set([EVENT_ID]));
  });

  it('does not retry once consent is withdrawn between attempts', async () => {
    const { tracker, fetchSpy, state } = setup([{ status: 503 }]);
    fetchSpy.mockImplementationOnce(async () => {
      state.consent = false;
      return new Response('{}', { status: 503 });
    });
    await expect(tracker.track('page.view')).resolves.toBe('skipped_no_consent');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ status: 422 }, 1], [{ status: 429 }, 1], [new TypeError('offline'), 2],
  ] as const)('%j -> failed without throwing (%i request)', async (response, calls) => {
    const { tracker, fetchSpy } = setup([response, response]);
    await expect(tracker.track('page.view')).resolves.toBe('failed');
    expect(fetchSpy).toHaveBeenCalledTimes(calls);
  });

  it('401 follows the existing auth policy (onUnauthorized) and is not retried', async () => {
    const { tracker, fetchSpy, onUnauthorized } = setup([{ status: 401 }]);
    await expect(tracker.track('page.view')).resolves.toBe('failed');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('keeps the screen working when the event API fails', async () => {
    const { tracker } = setup([{ status: 500 }, { status: 500 }]);
    function Counter({ t }: { t: BehaviorTracker }) {
      const [count, setCount] = useState(0);
      return <button onClick={() => { setCount((n) => n + 1); void t.track('page.view'); }}>clicked {count}</button>;
    }
    render(<Counter t={tracker} />);
    fireEvent.click(screen.getByRole('button'));
    fireEvent.click(screen.getByRole('button'));
    expect(await screen.findByText('clicked 2')).toBeInTheDocument();
  });
});
