import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockPortfolioBackend, type MockPortfolioBackend } from '../mocks/publicPortfolio';
import { PortfolioReaderContext, PortfolioServiceContext } from './portfolioContext';

/**
 * 공개 포트폴리오 데이터 경로 (T130).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter. 설정·공개 화면이 같은 Mock 저장소를 씁니다(routes.tsx).
 * - 그 밖: 실제 API(T129, migration 0007). 소유자 설정은 로그인 토큰이 붙은 HttpClient, 공개 화면(/p/:token)은
 *   로그인 없이 공개 조회 엔드포인트만 부릅니다(토큰 헤더 없음).
 * 이 Provider 는 env.publicPortfolioUi(기본 꺼짐)일 때만 라우트에 들어갑니다.
 */
export function PortfolioServiceProvider({ backend, children }: { backend?: MockPortfolioBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const [fallback] = useState(() => (backend || env.mockEnabled ? createMockPortfolioBackend({ latencyMs: 200 }) : null));
  const source = backend ?? fallback;
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const service = useMemo(() => {
    if (!userId) return null;
    return source ? source.serviceFor(userId) : api.publicPortfolio;
  }, [source, userId, api]);
  const reader = source ? source.reader : api.publicPortfolio;
  return (
    <PortfolioReaderContext.Provider value={reader}>
      <PortfolioServiceContext.Provider value={service}>
        {children ?? <Outlet />}
      </PortfolioServiceContext.Provider>
    </PortfolioReaderContext.Provider>
  );
}
