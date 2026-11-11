import { useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import type { CrawlerAdminService } from '../api/crawlerAdmin';
import { useApi } from '../api/ApiContext';
import { env } from '../config/env';
import { createMockCrawlerAdminService } from '../mocks/crawlerAdmin';
import { CrawlerAdminServiceContext } from './crawlerAdminContext';

/**
 * 크롤러 관리자 콘솔의 데이터 경로 (T156).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Adapter (합성 데이터, 네트워크 없음)
 * - 그 외: 로그인 세션의 HttpClient 로 T155 API 를 부릅니다. 서버가 admin 역할을 다시 검사합니다.
 * 이 Provider 는 env.crawlerAdminUi 플래그가 켜졌을 때만 라우트에 들어갑니다(기본 꺼짐).
 */
export function CrawlerAdminServiceProvider({ service, children }: { service?: CrawlerAdminService; children?: ReactNode }) {
  const api = useApi();
  const [mock] = useState(() => (env.mockEnabled ? createMockCrawlerAdminService({ latencyMs: 200 }) : null));
  return (
    <CrawlerAdminServiceContext.Provider value={service ?? mock ?? api.crawlerAdmin}>
      {children ?? <Outlet />}
    </CrawlerAdminServiceContext.Provider>
  );
}
