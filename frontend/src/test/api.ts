/** 화면 테스트용 API 도우미. 실제 화면과 같은 createApi 경로를 쓰고, 전송만 바꿉니다. */
import { vi } from 'vitest';
import { createApi, type Api } from '../api';
import { buildQuery, createHttpClient, type HttpClient, type HttpRequest } from '../api/http';
import { createMockFetch } from '../mocks/mockFetch';

/** 테스트가 받는 요청: path 에는 쿼리스트링까지 붙어 있고, init 에는 query 가 없습니다. */
export type RequestFn = (path: string, init?: Omit<HttpRequest, 'query'>) => Promise<unknown>;

/** 가상 데이터(mocks/handlers)를 쓰는 클라이언트. token 은 Mock 계정 토큰(예: mock-access-user@example.com). */
export const mockHttp = (token: string | null = null): HttpClient =>
  createHttpClient({ baseUrl: '/api', fetch: createMockFetch('/api'), getToken: () => token });

/** 요청을 "경로+쿼리스트링" 한 줄로 받는 가짜 전송으로 API 묶음을 만듭니다. */
export const apiFrom = (request: RequestFn): Api => createApi({
  request: ((path: string, { query, ...init }: HttpRequest = {}) =>
    request(`${path}${buildQuery(query)}`, init)) as HttpClient['request'],
});

/** 요청을 기록하는 spy. 기본 동작은 주어진 클라이언트(기본: 로그인한 Mock 사용자)로 보냅니다. */
export const spyRequest = (impl?: RequestFn, http: HttpClient = mockHttp('mock-access-user@example.com')) =>
  vi.fn<RequestFn>(impl ?? ((path, init) => http.request(path, init)));
