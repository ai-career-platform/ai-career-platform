import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { createMockApplicationBackend, type MockApplicationBackend } from '../mocks/jobApplications';
import { ApplicationServiceContext } from './applicationContext';

/**
 * 지원 현황 화면의 데이터 경로 (T103).
 * - 지금: 메모리 Mock Adapter. env.applicationsUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - 로그인 사용자 ID 별로 서비스를 만듭니다(다른 사용자 기록과 섞이지 않음).
 * - 실제 API(T102, 플래그 기본 꺼짐) 연결은 T101 승인 후 여기 한 곳에서 createHttpJobApplicationService 로 바꿉니다.
 */
export function ApplicationServiceProvider({ backend, children }: { backend?: MockApplicationBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const [fallback] = useState(() => createMockApplicationBackend({ latencyMs: 200 }));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => (userId ? source.serviceFor(userId) : null), [source, userId]);
  return (
    <ApplicationServiceContext.Provider value={service}>
      {children ?? <Outlet />}
    </ApplicationServiceContext.Provider>
  );
}
