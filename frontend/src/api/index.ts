import { catalogApi } from './catalog';
import type { HttpClient } from './http';
import { meApi } from './me';

/** 도메인별 엔드포인트 묶음. 같은 HttpClient(토큰·mock 설정)를 공유합니다. */
export function createApi(http: HttpClient) {
  return { ...catalogApi(http), me: meApi(http) };
}

export type Api = ReturnType<typeof createApi>;
