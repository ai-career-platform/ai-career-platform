import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockNotificationBackend, type MockNotificationBackend } from '../mocks/notifications';
import { NotificationServiceContext } from './notificationContext';

/**
 * 알림함·수신 설정 화면의 데이터 경로 (T97).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter, **로그인한 사용자 ID 별** 저장소(다른 사용자 알림·설정과 섞이지 않음).
 * - 그 밖: 실제 API(T97, 로그인 토큰이 붙은 HttpClient). 본인 알림·설정만 서버가 돌려줍니다.
 * 이 Provider 는 env.notificationsUi(기본 꺼짐)일 때만 라우트에 들어갑니다.
 */
export function NotificationServiceProvider({ backend, children }: { backend?: MockNotificationBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const [fallback] = useState(() => (backend || env.mockEnabled ? createMockNotificationBackend({ latencyMs: 200 }) : null));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => {
    if (!userId) return null;
    return source ? source.serviceFor(userId) : api.notifications;
  }, [source, userId, api]);
  return (
    <NotificationServiceContext.Provider value={service}>
      {children ?? <Outlet />}
    </NotificationServiceContext.Provider>
  );
}
