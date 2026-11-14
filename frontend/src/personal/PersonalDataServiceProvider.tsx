import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockPersonalDataBackend, type MockPersonalDataBackend } from '../mocks/personalData';
import { PersonalDataServiceContext } from './personalDataContext';

/**
 * 내 데이터 반출 데이터 경로 (T143).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter, 로그인 사용자별 저장소(합성 데이터만).
 * - 그 밖: 실제 API(T142, 로그인 토큰이 붙은 HttpClient). 본인 요청만 서버가 돌려줍니다.
 * 이 Provider 는 env.personalDataUi(기본 꺼짐)일 때만 라우트에 들어갑니다.
 */
export function PersonalDataServiceProvider({ backend, children }: { backend?: MockPersonalDataBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const [fallback] = useState(() => (backend || !env.mockEnabled ? null
    : createMockPersonalDataBackend({ latencyMs: 200, processingMs: 3000 })));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => {
    if (!userId) return null;
    return source ? source.serviceFor(userId) : api.personalData;
  }, [source, userId, api]);
  return (
    <PersonalDataServiceContext.Provider value={service}>
      {children ?? <Outlet />}
    </PersonalDataServiceContext.Provider>
  );
}
