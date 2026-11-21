import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockCompanyBackend } from '../mocks/companyAccounts';
import { createMockPostingBackend, type MockPostingBackend } from '../mocks/companyPostings';
import { useMockCompanyBackend } from './companyContext';
import { PostingBackendContext, PostingServiceContext } from './postingContext';

/**
 * 기업 공고 데이터 경로 (T127). CompanyServiceProvider 안쪽에 둡니다.
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter. 같은 기업 Mock(소속·조직 상태)을 씁니다.
 * - 그 밖: 실제 API(T126, migration 0009, 서버 COMPANY_POSTINGS_API=true 필요). 공개 게시는 운영 승인 때만 됩니다.
 * 이 Provider 는 env.companyPostingsUi(기본 꺼짐, 기업 콘솔 플래그 필요)일 때만 라우트에 들어갑니다.
 */
export function PostingServiceProvider({ backend, children }: { backend?: MockPostingBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const company = useMockCompanyBackend();
  const [source] = useState(() => backend ?? (env.mockEnabled
    ? createMockPostingBackend(company ?? createMockCompanyBackend(), { latencyMs: 200 }) : null));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const service = useMemo(() => {
    if (!userId) return null;
    return source ? source.serviceFor(userId) : api.companyPostings;
  }, [source, userId, api]);
  return (
    <PostingBackendContext.Provider value={source}>
      <PostingServiceContext.Provider value={service}>
        {children ?? <Outlet />}
      </PostingServiceContext.Provider>
    </PostingBackendContext.Provider>
  );
}
