import { ApiError } from '../api/errors';
import { resolveDocumentsMock } from './documents';
import { resolveMarketTrendsMock } from './marketTrends';
import { resolvePrivacyMock } from './privacy';
import { resolveCareerWorkspaceMock } from './careerWorkspace';
import { resolveRecommendationMock } from './recommendations';
import { resolveSkillsMock } from './skills';

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

/** 로그인이 필요한 도메인 Mock. 경로가 맞으면 먼저 토큰을 확인합니다(없으면 401). */
function resolveAuthed(path: string, { method, body, token }: MockRequest): unknown {
  if (path.startsWith('/v1/recommendation-runs')) {
    return resolveRecommendationMock(path, method, body, authedUser(token).email);
  }
  if (path.startsWith('/v1/market-trends')) {
    authedUser(token);
    return resolveMarketTrendsMock(path);
  }
  return null;
}

/** Backend 카탈로그(app/core/errors.py ERROR_CATALOG)와 같은 사용자 문구 — Mock에서도 화면 문구를 실제와 맞춘다 */
const mockMessages: Record<string, string> = {
  UNAUTHENTICATED: '로그인이 필요합니다.',
  VALIDATION_FAILED: '입력값을 확인해 주세요.',
  DUPLICATE_SKILL: '같은 기술이 중복으로 들어 있습니다.',
  NOT_FOUND: '요청한 정보를 찾을 수 없습니다.',
  DOCUMENT_NOT_READY: '문서를 아직 사용할 수 없습니다. 검사가 끝난 뒤 다시 시도해 주세요.',
  FILE_TOO_LARGE: '파일은 10MB 이하만 올릴 수 있습니다.',
  UNSUPPORTED_FILE_TYPE: 'PDF 또는 DOCX 파일만 올릴 수 있습니다.',
};

const MOCK_DELAY_MS = 150;

export async function resolveMock<T>(
  path: string,
  request: MockRequest = { method: 'GET' },
): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  try {
    if (path === '/v1/documents' || path.startsWith('/v1/documents?') || path.startsWith('/v1/documents/')) {
      const result = resolveDocumentsMock(path, request, authedUser(request.token).email);
      if (result instanceof Blob) return result as T;
      if (result !== null) return structuredClone(result) as T;
    }
    if (['/v1/me/consents', '/v1/me/deletion-request', '/v1/consent-policies'].includes(path)) {
      const userKey = path === '/v1/consent-policies' ? null : authedUser(request.token).email;
      return structuredClone(resolvePrivacyMock(path, request, userKey)) as T;
    }
    if (path.startsWith('/v1/skills') || path === '/v1/me/skills') {
      const userKey = path === '/v1/me/skills' ? authedUser(request.token).email : null;
      const result = resolveSkillsMock(path, request, userKey);
      if (result !== null) return structuredClone(result) as T;
    }
    if (path.startsWith('/v1/me/') || path.startsWith('/v1/job-roles')) {
      authedUser(request.token);
      const workspaceResult = resolveCareerWorkspaceMock(path, request);
      if (workspaceResult !== null) return structuredClone(workspaceResult) as T;
    }
    const authResult = resolveAuth(path, request);
    if (authResult !== null) return structuredClone(authResult) as T;
    const authedResult = resolveAuthed(path, request);
    if (authedResult !== null) return structuredClone(authedResult) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw new ApiError(error.status, path, undefined, error.code, error.code ? mockMessages[error.code] : undefined);
    }
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
