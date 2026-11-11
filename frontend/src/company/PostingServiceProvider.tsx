import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { createMockCompanyBackend } from '../mocks/companyAccounts';
import { createMockPostingBackend, type MockPostingBackend } from '../mocks/companyPostings';
import { useMockCompanyBackend } from './companyContext';
import { PostingBackendContext, PostingServiceContext } from './postingContext';

/**
 * 기업 공고 데이터 경로 (T127). CompanyServiceProvider 안쪽에 두어 같은 기업 Mock(소속·조직 상태)을 씁니다.
 * 실제 API(T126, 플래그 기본 꺼짐·저장소 없음) 연결은 T125 승인·migration 후 여기서 createHttpCompanyPostingService 로.
 */
export function PostingServiceProvider({ backend, children }: { backend?: MockPostingBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const company = useMockCompanyBackend();
  const [source] = useState(() => backend ?? createMockPostingBackend(company ?? createMockCompanyBackend(), { latencyMs: 200 }));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const service = useMemo(() => (userId ? source.serviceFor(userId) : null), [source, userId]);
  return (
    <PostingBackendContext.Provider value={source}>
      <PostingServiceContext.Provider value={service}>
        {children ?? <Outlet />}
      </PostingServiceContext.Provider>
    </PostingBackendContext.Provider>
  );
}
