import { authApi } from './auth';
import { behaviorEventsApi } from './behaviorEvents';
import { catalogApi } from './catalog';
import { createHttpCrawlerAdminService } from './crawlerAdminHttp';
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
    // T156 크롤러 관리자(T155 API). 화면은 VITE_CRAWLER_ADMIN_UI 플래그가 켜졌을 때만 씁니다.
    crawlerAdmin: createHttpCrawlerAdminService(http),
  };
}

export type Api = ReturnType<typeof createApi>;
