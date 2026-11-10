import { authApi } from './auth';
import { behaviorEventsApi } from './behaviorEvents';
import { catalogApi } from './catalog';
import { documentsApi } from './documents';
import { systemApi } from './health';
import type { HttpClient } from './http';
import { marketTrendsApi } from './marketTrends';
import { meApi } from './me';
import { recommendationsApi } from './recommendations';

/** 도메인별 엔드포인트 묶음. 같은 HttpClient(토큰·mock 설정)를 공유합니다. */
export function createApi(http: HttpClient) {
  return {
    ...catalogApi(http), auth: authApi(http), behaviorEvents: behaviorEventsApi(http), documents: documentsApi(http), marketTrends: marketTrendsApi(http), me: meApi(http),
    recommendations: recommendationsApi(http), system: systemApi(http),
  };
}

export type Api = ReturnType<typeof createApi>;
