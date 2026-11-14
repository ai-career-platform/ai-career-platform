import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockCompanyBackend, type MockCompanyBackend } from '../mocks/companyAccounts';
import { CompanyBackendContext, CompanyServiceContext } from './companyContext';

/**
 * 기업 콘솔 데이터 경로 (T124).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter. 로그인 사용자 ID 별로 서비스를 만들고, Mock 메일함(초대 링크)과
 *   기업 공고 Mock(T127, PostingServiceProvider)이 같은 Mock 저장소를 씁니다.
 * - 그 밖: 실제 API(T123, migration 0008). 로그인 토큰이 붙은 HttpClient 를 씁니다. Mock 메일함은 없습니다(null).
 * 이 Provider 는 env.companyConsoleUi(기본 꺼짐)일 때만 라우트에 들어갑니다.
 */
export function CompanyServiceProvider({ backend, children }: { backend?: MockCompanyBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const [fallback] = useState(() => (backend || env.mockEnabled ? createMockCompanyBackend({ latencyMs: 200 }) : null));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => {
    if (!userId) return null;
    return source ? source.serviceFor(userId) : api.companyAccounts;
  }, [source, userId, api]);
  return (
    <CompanyBackendContext.Provider value={source}>
      <CompanyServiceContext.Provider value={service}>
        {children ?? <Outlet />}
      </CompanyServiceContext.Provider>
    </CompanyBackendContext.Provider>
  );
}
