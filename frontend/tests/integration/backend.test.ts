import { spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { apiGet, ApiError } from '../../src/api/client';
import { getHealth, getVersion } from '../../src/api/health';

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
const runner = fileURLToPath(new URL('../../../tests/integration/serve_backend.py', import.meta.url));
const options = { mockEnabled: false, baseUrl: '' };
let backend: ChildProcess | undefined;

async function stopBackend() {
  if (!backend?.pid || backend.exitCode !== null || backend.signalCode !== null) return;
  const exited = once(backend, 'exit');
  backend.kill();
  await exited;
}

beforeAll(async () => {
  const child = spawn(process.env.INTEGRATION_PYTHON || 'python', ['-B', runner], {
    cwd: repoRoot,
    env: {
      ...process.env,
      APP_ENV: 't29-local-integration',
      APP_VERSION: 't29-http-regression',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  backend = child;
  let output = '';
  let spawnError: Error | undefined;
  child.on('error', (error) => { spawnError = error; });
  child.stdout!.on('data', (chunk: Buffer) => { output += chunk.toString(); });
  // Readiness is established by HTTP, not by the process starting or printing a URL.
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    if (spawnError) throw spawnError;
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error('Local Backend exited before readiness; check INTEGRATION_PYTHON and backend dependencies.');
    }
    const match = output.match(/T29_URL=(http:\/\/127\.0\.0\.1:\d+)/);
    if (match) {
      options.baseUrl = match[1]!;
      try {
        const response = await fetch(`${options.baseUrl}/health`, { signal: AbortSignal.timeout(1000) });
        if (response.ok) return;
      } catch { /* Wait for uvicorn startup. */ }
    }
    await delay(50);
  }
  throw new Error('Local Backend did not become healthy within 15 seconds.');
});

afterAll(stopBackend);

describe('T29: frontend client → real local Backend HTTP (mock disabled)', () => {
  it('reads the health DTO through the production frontend client', async () => {
    expect(await getHealth(options)).toEqual({ status: 'ok', service: 'ai-career-backend' });
  });

  it('reads the injected application version rather than mock fixture values', async () => {
    expect(await getVersion(options)).toEqual({
      application: 'ai-career-platform',
      environment: 't29-local-integration',
      version: 't29-http-regression',
    });
  });

  it('serves runtime OpenAPI for the health and version APIs', async () => {
    const spec = await apiGet<{ paths: Record<string, unknown>; info: { version: string } }>('/openapi.json', options);
    expect(spec.paths).toHaveProperty('/health');
    expect(spec.paths).toHaveProperty('/version');
    expect(spec.info.version).toBe('t29-http-regression');
  });

  it('preserves real 404 status and path in ApiError', async () => {
    await expect(apiGet('/__t29_missing__', options)).rejects.toMatchObject({
      name: 'ApiError', status: 404, path: '/__t29_missing__',
    });
  });

  it('returns the public error DTO without framework error details', async () => {
    const response = await fetch(`${options.baseUrl}/__t29_missing__`);
    expect(response.status).toBe(404);
    expect(response.headers.get('content-type')).toContain('application/json');
    expect(await response.json()).toEqual({ code: 'NOT_FOUND', status: 404, message: '요청한 정보를 찾을 수 없습니다.' });
    expect(response.headers.get('x-request-id')).toMatch(/^req-[0-9a-f]{16}$/);
  });

  it('rejects writes to a read-only system API with 405 and Allow', async () => {
    const response = await fetch(`${options.baseUrl}/health`, { method: 'POST' });
    expect(response.status).toBe(405);
    expect(response.headers.get('allow')).toContain('GET');
    expect(await response.json()).toMatchObject({ code: 'METHOD_NOT_ALLOWED', status: 405 });
  });

  it('keeps a safe caller request ID across the HTTP boundary', async () => {
    const response = await fetch(`${options.baseUrl}/health`, { headers: { 'X-Request-ID': 't29-request-12345' } });
    expect(response.status).toBe(200);
    expect(response.headers.get('x-request-id')).toBe('t29-request-12345');
  });

  it('replaces an unsafe request ID before returning it', async () => {
    const response = await fetch(`${options.baseUrl}/health`, { headers: { 'X-Request-ID': '<invalid-id>' } });
    expect(response.headers.get('x-request-id')).toMatch(/^req-[0-9a-f]{16}$/);
  });

  it('reports status 0 when the actual Backend process is stopped', async () => {
    await stopBackend();
    const error = await getHealth(options).catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 0, path: '/health' });
  });
});
