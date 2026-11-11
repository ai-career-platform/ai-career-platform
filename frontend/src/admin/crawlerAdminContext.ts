import { createContext, useContext } from 'react';
import type { CrawlerAdminService } from '../api/crawlerAdmin';

/** 크롤러 관리자 콘솔(T156)이 쓰는 서비스. Mock 모드면 메모리 Adapter, 아니면 T155 실제 API Adapter 입니다. */
export const CrawlerAdminServiceContext = createContext<CrawlerAdminService | null>(null);

export function useCrawlerAdminService(): CrawlerAdminService {
  const service = useContext(CrawlerAdminServiceContext);
  if (!service) throw new Error('useCrawlerAdminService must be used inside <CrawlerAdminServiceProvider>');
  return service;
}
