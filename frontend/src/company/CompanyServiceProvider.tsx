import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { createMockCompanyBackend, type MockCompanyBackend } from '../mocks/companyAccounts';
import { CompanyBackendContext, CompanyServiceContext } from './companyContext';

/**
 * 기업 콘솔 데이터 경로 (T124).
 * - 지금: 메모리 Mock Adapter. env.companyConsoleUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - 로그인 사용자 ID 별로 서비스를 만듭니다. 실제 API(T123, 플래그 기본 꺼짐·저장소 없음) 연결은
 *   T122 승인·migration 후 여기 한 곳에서 createHttpCompanyAccountService 로 바꿉니다.
 */
export function CompanyServiceProvider({ backend, children }: { backend?: MockCompanyBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const [fallback] = useState(() => createMockCompanyBackend({ latencyMs: 200 }));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => (userId ? source.serviceFor(userId) : null), [source, userId]);
  return (
    <CompanyBackendContext.Provider value={source}>
      <CompanyServiceContext.Provider value={service}>
        {children ?? <Outlet />}
      </CompanyServiceContext.Provider>
    </CompanyBackendContext.Provider>
  );
}
