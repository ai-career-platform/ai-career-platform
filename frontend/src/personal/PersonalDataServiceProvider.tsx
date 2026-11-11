import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { createMockPersonalDataBackend, type MockPersonalDataBackend } from '../mocks/personalData';
import { PersonalDataServiceContext } from './personalDataContext';

/**
 * 내 데이터 반출 데이터 경로 (T143).
 * - 지금: 메모리 Mock Adapter. env.personalDataUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - 실제 API(T142, 플래그 기본 꺼짐·저장소 없음) 연결은 T141 승인·migration 후 여기 한 곳에서 바꿉니다.
 */
export function PersonalDataServiceProvider({ backend, children }: { backend?: MockPersonalDataBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const [source] = useState(() => backend ?? createMockPersonalDataBackend({ latencyMs: 200, processingMs: 3000 }));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const service = useMemo(() => (userId ? source.serviceFor(userId) : null), [source, userId]);
  return (
    <PersonalDataServiceContext.Provider value={service}>
      {children ?? <Outlet />}
    </PersonalDataServiceContext.Provider>
  );
}
