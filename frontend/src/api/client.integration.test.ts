/// <reference types="node" />
// @vitest-environment node
// Opt-in read-only HTTP checks through the existing Vite /api proxy.
// Start `npm run dev` in real API mode first; this suite never starts servers,
// creates users, changes profiles, or uses fetch/MSW mocks.
import { env as processEnv } from 'node:process';
import { beforeAll, describe, expect, it } from 'vitest';
import { env } from '../config/env';
import { ApiError, apiGet } from './client';
import { getDbHealth, getHealth, getVersion } from './health';

const origin = processEnv.T29_REAL_API_ORIGIN;

describe.skipIf(!origin)('T29 real API through existing Vite proxy', () => {
  const options = { baseUrl: `${origin}/api`, mockEnabled: false };

  beforeAll(() => {
    const url = new URL(origin!);
    // Require the local existing development proxy, not a direct Staging URL.
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)
      || url.pathname !== '/' || url.search || url.hash || url.username || url.password
      || env.apiBaseUrl !== '/api' || env.mockEnabled) {
      throw new Error('T29 requires a loopback Vite origin, /api base and real API mode');
    }
  });

  it('decodes actual Backend Health and Version DTOs over /api', async () => {
    await expect(getHealth(options)).resolves.toEqual({
      status: 'ok', service: 'ai-career-backend',
    });
    const version = await getVersion(options);
    expect(version.application).toBe('ai-career-platform');
    expect(version.environment).not.toBe('mock');
    expect(version.version).toMatch(/^[a-f0-9]{40}$/);
  });

  it('receives actual PostgreSQL DB Health instead of a fixture', async () => {
    await expect(getDbHealth(options)).resolves.toEqual({
      status: 'ok', service: 'ai-career-database',
    });
  });

  it('finds merged GET/PATCH profile routes in actual OpenAPI', async () => {
    const spec = await apiGet<{ paths: Record<string, Record<string, unknown>> }>(
      '/openapi.json', options,
    );
    expect(spec.paths['/api/v1/me']).toHaveProperty('get');
    expect(spec.paths['/api/v1/me']).toHaveProperty('patch');
  });

  it.each([
    { name: 'unauthenticated profile', path: '/v1/me', status: 401 },
    { name: 'missing resource', path: '/v1/t29-missing-resource', status: 404 },
    { name: 'invalid read-only query', path: '/jobs/collected?limit=0', status: 422 },
  ])('maps real $status for $name to ApiError', async ({ path, status }) => {
    const error: unknown = await apiGet(path, options).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status, path });
  });
});
