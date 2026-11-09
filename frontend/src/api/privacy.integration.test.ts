/// <reference types="node" />
// @vitest-environment node
// T32 opt-in, read-only checks against a local real-API Vite proxy.
// Never creates accounts, writes consents, requests deletion, or accesses Staging directly.
import { env as processEnv } from 'node:process';
import { beforeAll, describe, expect, it } from 'vitest';
import { env } from '../config/env';
import { ApiError } from './client';
import { createHttpClient } from './http';
import type { ConsentPolicy } from './privacy';

const origin = processEnv.T29_REAL_API_ORIGIN;

describe.skipIf(!origin)('T32 read-only real API contract (no credentials or DB mutations)', () => {
  const http = createHttpClient({ baseUrl: `${origin}/api` });

  beforeAll(() => {
    const url = new URL(origin!);
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)
      || url.protocol !== 'http:'
      || url.pathname !== '/' || url.search || url.hash || url.username || url.password
      || env.apiBaseUrl !== '/api' || env.mockEnabled) {
      throw new Error('T32 requires loopback HTTP Vite origin, /api base and real API mode');
    }
  });

  it('exposes the merged T31 API operations and explicit cancellation HOLD', async () => {
    const spec = await http.request<{ paths: Record<string, Record<string, {
      'x-implementation-status'?: string
    }>> }>('/openapi.json');
    expect(spec.paths['/api/v1/me/consents']).toHaveProperty('get');
    expect(spec.paths['/api/v1/me/consents']).toHaveProperty('post');
    expect(spec.paths['/api/v1/me/deletion-request']).toHaveProperty('get');
    expect(spec.paths['/api/v1/me/deletion-request']).toHaveProperty('post');
    expect(spec.paths['/api/v1/me/deletion-request']?.delete?.['x-implementation-status']).toBe('HOLD');
  });

  it('reads consent policy metadata without modifying PostgreSQL', async () => {
    const policies = await http.request<ConsentPolicy[]>('/v1/consent-policies');
    expect(Array.isArray(policies)).toBe(true);
    for (const policy of policies) {
      expect(policy).toEqual(expect.objectContaining({
        policy_code: expect.any(String),
        version: expect.any(String),
        is_required: expect.any(Boolean),
      }));
    }
  });

  it.each(['/v1/me/consents', '/v1/me/deletion-request'])(
    'rejects unauthenticated GET %s with HTTP 401', async path => {
      const error = await http.request(path).catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ status: 401, path });
    },
  );
});
