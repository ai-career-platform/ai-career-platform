import { authApi } from './auth';
import { catalogApi } from './catalog';
import { systemApi } from './health';
import type { HttpClient } from './http';
import { meApi } from './me';
import { skillGapsApi } from './skillGaps';

/** 도메인별 엔드포인트 묶음. 같은 HttpClient(토큰·mock 설정)를 공유합니다. */
export function createApi(http: HttpClient) {
  return { ...catalogApi(http), auth: authApi(http), me: meApi(http), skillGaps: skillGapsApi(http), system: systemApi(http) };
}

export type Api = ReturnType<typeof createApi>;
