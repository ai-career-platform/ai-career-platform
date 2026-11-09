import { ApiError } from '../api/errors';

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

const problem = (status: number, code: string): never => {
  throw new ApiError(status, '', undefined, code);
};

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
  if (method === 'GET' && path === '/v1/me') {
    const { email, display_name } = authedUser(token);
    return { user_id: email, email, display_name, status: 'active' };
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
    if (error instanceof ApiError) throw new ApiError(error.status, path, undefined, error.code);
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
