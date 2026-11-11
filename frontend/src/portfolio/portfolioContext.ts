import { createContext, useContext } from 'react';
import type { PortfolioService, PublicPortfolioReader } from '../api/publicPortfolio';

/** 로그인 사용자의 공개 프로필 설정 서비스 (T130). 지금은 Mock Adapter 만 연결됩니다. */
export const PortfolioServiceContext = createContext<PortfolioService | null>(null);
/** 공개 화면(로그인 없음) 읽기 전용 */
export const PortfolioReaderContext = createContext<PublicPortfolioReader | null>(null);

export function usePortfolioService(): PortfolioService {
  const service = useContext(PortfolioServiceContext);
  if (!service) throw new Error('usePortfolioService must be used inside <PortfolioServiceProvider> after login');
  return service;
}

export function usePortfolioReader(): PublicPortfolioReader {
  const reader = useContext(PortfolioReaderContext);
  if (!reader) throw new Error('usePortfolioReader must be used inside <PortfolioServiceProvider>');
  return reader;
}
