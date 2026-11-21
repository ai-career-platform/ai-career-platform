import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockApplicationBackend, type MockApplicationBackend } from '../mocks/jobApplications';
import { ApplicationServiceContext } from './applicationContext';

/**
 * 지원 현황 화면의 데이터 경로 (T103).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter, 로그인 사용자 ID 별 저장소(다른 사용자 기록과 섞이지 않음).
 * - 그 밖: 실제 API(T102, 로그인 토큰이 붙은 HttpClient). 본인 기록만 서버가 돌려줍니다.
 * 이 Provider 는 env.applicationsUi(기본 꺼짐)일 때만 라우트에 들어갑니다.
 */
export function ApplicationServiceProvider({ backend, children }: { backend?: MockApplicationBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const [fallback] = useState(() => (backend || env.mockEnabled ? createMockApplicationBackend({ latencyMs: 200 }) : null));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => {
    if (!userId) return null;
    return source ? source.serviceFor(userId) : api.jobApplications;
  }, [source, userId, api]);
  return (
    <ApplicationServiceContext.Provider value={service}>
      {children ?? <Outlet />}
    </ApplicationServiceContext.Provider>
  );
}
