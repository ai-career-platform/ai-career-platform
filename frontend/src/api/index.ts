import { authApi } from './auth';
import { catalogApi } from './catalog';
import { documentsApi } from './documents';
import { systemApi } from './health';
import type { HttpClient } from './http';
import { matchesApi } from './matches';
import { meApi } from './me';

/** 도메인별 엔드포인트 묶음. 같은 HttpClient(토큰·mock 설정)를 공유합니다. */
export function createApi(http: HttpClient) {
  return {
    ...catalogApi(http), auth: authApi(http), documents: documentsApi(http), matches: matchesApi(http), me: meApi(http), system: systemApi(http),
  };
}

export type Api = ReturnType<typeof createApi>;
