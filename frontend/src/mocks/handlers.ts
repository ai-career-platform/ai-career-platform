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

const MOCK_DELAY_MS = 150;

export async function resolveMock<T>(path: string): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  const entry = mockRoutes[path];
  if (!entry) {
    throw new ApiError(404, path, `No mock for ${path}`);
  }
  if (entry.status >= 400) {
    throw new ApiError(entry.status, path);
  }
  return structuredClone(entry.body) as T;
}
