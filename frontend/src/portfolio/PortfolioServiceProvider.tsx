import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { createMockPortfolioBackend, type MockPortfolioBackend } from '../mocks/publicPortfolio';
import { PortfolioReaderContext, PortfolioServiceContext } from './portfolioContext';

/**
 * 공개 포트폴리오 데이터 경로 (T130).
 * - 지금: 메모리 Mock Adapter. env.publicPortfolioUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - 소유자 설정은 로그인 사용자 ID 별 서비스, 공개 화면(/p/:token)은 로그인 없이 읽기 전용 reader.
 * - 실제 API(T129, 플래그 기본 꺼짐·저장소 없음) 연결은 T128 승인·migration 후 여기 한 곳에서 바꿉니다.
 */
export function PortfolioServiceProvider({ backend, children }: { backend?: MockPortfolioBackend; children?: ReactNode }) {
  const { state } = useAuth();
  // 공개 화면과 설정 화면이 같은 Provider 아래에 있어(routes.tsx) 같은 Mock 저장소를 씁니다.
  const [source] = useState(() => backend ?? createMockPortfolioBackend({ latencyMs: 200 }));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const service = useMemo(() => (userId ? source.serviceFor(userId) : null), [source, userId]);
  return (
    <PortfolioReaderContext.Provider value={source.reader}>
      <PortfolioServiceContext.Provider value={service}>
        {children ?? <Outlet />}
      </PortfolioServiceContext.Provider>
    </PortfolioReaderContext.Provider>
  );
}
