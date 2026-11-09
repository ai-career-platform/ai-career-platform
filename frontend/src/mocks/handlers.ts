import { ApiError } from '../api/errors';
import type { FieldError } from '../api/errors';

/**
 * 개발용 가상 데이터. 실제 개인정보·운영 데이터를 넣지 않습니다.
 * 새 화면은 docs/API_CONTRACT.md의 Request/Response를 기준으로 여기에 fixture를 추가하고,
 * 실제 API가 구현되면 VITE_API_MOCK=false 로 전환해 검증합니다.
 * Mock 성공은 실제 서비스 PASS가 아닙니다.
 */
type MockEntry = { status: number; body?: unknown };

export const mockRoutes: Record<string, MockEntry> = {
  '/health': { status: 200, body: { status: 'ok', service: 'ai-career-backend' } },
  '/version': {
    status: 200,
    body: { application: 'ai-career-platform', environment: 'mock', version: '0.0.0-mock' },
  },
  '/health/db': { status: 200, body: { status: 'ok', service: 'ai-career-database' } },
};

/** 로그인 Mock 계정 (T15 인증 API 구현 전까지만 사용). 비밀번호는 모두 공통 가짜 값입니다. */
export const MOCK_PASSWORD = 'mock-password-1234';
const mockUsers: Record<string, { display_name: string; roles: string[] }> = {
  'user@example.com': { display_name: '일반 사용자', roles: ['job_seeker'] },
  'admin@example.com': { display_name: '운영 관리자', roles: ['job_seeker', 'admin'] },
};
const MOCK_TOKEN_PREFIX = 'mock-access-';

export interface MockRequest {
  method: string;
  body?: unknown;
  token?: string | null;
}

const problem = (status: number, code: string, errors: FieldError[] = []): never => {
  throw new ApiError(status, '', undefined, code, errors);
};

/** 프로필 Mock 저장소 (메모리). 화면을 새로고침하면 초기값으로 돌아갑니다. */
interface MockProfile {
  display_name: string;
  headline: string | null;
  bio: string | null;
  location_text: string | null;
}
const initialProfiles = (): Record<string, MockProfile> => ({
  'user@example.com': { display_name: '일반 사용자', headline: '백엔드 개발자 지망생', bio: null, location_text: '서울' },
  'admin@example.com': { display_name: '운영 관리자', headline: null, bio: null, location_text: null },
});
let profiles = initialProfiles();
let failNext: { status: number; method: string } | null = null;

/** 테스트·개발용: Mock 상태를 처음으로 되돌립니다. */
export function resetMockState() {
  profiles = initialProfiles();
  failNext = null;
}
/** 테스트·개발용: 다음 /v1/me 요청(GET 또는 PATCH) 한 번을 지정한 HTTP 상태로 실패시킵니다. */
export function failNextProfileRequest(method: 'GET' | 'PATCH', status: number) {
  failNext = { status, method };
}

const LIMITS: Record<keyof MockProfile, number> = { display_name: 100, headline: 200, bio: 5000, location_text: 120 };

const profileOf = (email: string): MockProfile => profiles[email] ?? problem(404, 'NOT_FOUND');

function patchProfile(email: string, body: unknown): MockProfile {
  const patch = (body ?? {}) as Record<string, unknown>;
  const keys = Object.keys(patch);
  const errors: FieldError[] = [];
  if (keys.length === 0) errors.push({ field: 'body', code: 'INVALID' });
  for (const key of keys) {
    const value = patch[key];
    if (!(key in LIMITS)) errors.push({ field: key, code: 'UNKNOWN_FIELD' });
    else if (key === 'display_name' && (typeof value !== 'string' || value.trim() === '')) {
      errors.push({ field: key, code: 'REQUIRED' });
    } else if (value !== null && (typeof value !== 'string' || value.length > LIMITS[key as keyof MockProfile])) {
      errors.push({ field: key, code: 'TOO_LONG' });
    }
  }
  if (errors.length > 0) problem(422, 'VALIDATION_FAILED', errors);
  const next = { ...profileOf(email), ...(patch as Partial<MockProfile>) };
  profiles[email] = next;
  return next;
}

function authedUser(token?: string | null) {
  const email = token?.startsWith(MOCK_TOKEN_PREFIX) ? token.slice(MOCK_TOKEN_PREFIX.length) : '';
  const user = mockUsers[email];
  return user ? { email, ...user } : problem(401, 'UNAUTHENTICATED');
}

function resolveAuth(path: string, { method, body, token }: MockRequest): unknown {
  if (method === 'POST' && path === '/v1/auth/login') {
    const { email, password } = (body ?? {}) as { email?: string; password?: string };
    if (email === 'locked@example.com') return problem(429, 'RATE_LIMITED');
    if (!email || !mockUsers[email] || password !== MOCK_PASSWORD) return problem(401, 'INVALID_CREDENTIALS');
    return { access_token: `${MOCK_TOKEN_PREFIX}${email}`, token_type: 'Bearer', expires_in: 900 };
  }
  // Mock 에는 refresh 쿠키가 없으므로 새로고침하면 로그아웃 상태로 돌아갑니다.
  if (method === 'POST' && path === '/v1/auth/refresh') return problem(401, 'UNAUTHENTICATED');
  if (method === 'POST' && path === '/v1/auth/logout') return undefined;
  if (path === '/v1/me' && (method === 'GET' || method === 'PATCH')) {
    const { email } = authedUser(token);
    if (failNext?.method === method) {
      const { status } = failNext;
      failNext = null;
      return problem(status, 'INTERNAL_ERROR');
    }
    const { display_name, ...profile } = method === 'PATCH' ? patchProfile(email, body) : profileOf(email);
    return { user_id: email, email, display_name, status: 'active', profile };
  }
  if (method === 'GET' && path === '/v1/me/permissions') {
    return { roles: authedUser(token).roles, permissions: [] };
  }
  return null;
}

const MOCK_DELAY_MS = 150;

export async function resolveMock<T>(
  path: string,
  request: MockRequest = { method: 'GET' },
): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  try {
    const authResult = resolveAuth(path, request);
    if (authResult !== null) return structuredClone(authResult) as T;
  } catch (error) {
    if (error instanceof ApiError) throw new ApiError(error.status, path, undefined, error.code, error.errors);
    throw error;
  }
  const entry = request.method === 'GET' ? mockRoutes[path] : undefined;
  if (!entry) {
    throw new ApiError(404, path, `No mock for ${path}`);
  }
  if (entry.status >= 400) {
    throw new ApiError(entry.status, path);
  }
  return structuredClone(entry.body) as T;
}
