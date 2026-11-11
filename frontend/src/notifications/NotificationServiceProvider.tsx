import { useMemo, useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { createMockNotificationBackend, type MockNotificationBackend } from '../mocks/notifications';
import { NotificationServiceContext } from './notificationContext';

/**
 * 알림함·수신 설정 화면의 데이터 경로 (T97).
 * - 지금: 메모리 Mock Adapter. 이 Provider 는 env.notificationsUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - 서비스는 **로그인한 사용자 ID 별로** 만듭니다 — 다른 사용자의 알림·설정이 섞이지 않습니다.
 * - 실제 API 연결(알림함 계약 승인 + 서버 구현 후): 여기 한 곳에서 HTTP Adapter 로 바꿉니다.
 */
export function NotificationServiceProvider({ backend, children }: { backend?: MockNotificationBackend; children?: ReactNode }) {
  const { state } = useAuth();
  const [fallback] = useState(() => createMockNotificationBackend({ latencyMs: 200 }));
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const source = backend ?? fallback;
  const service = useMemo(() => (userId ? source.serviceFor(userId) : null), [source, userId]);
  return (
    <NotificationServiceContext.Provider value={service}>
      {children ?? <Outlet />}
    </NotificationServiceContext.Provider>
  );
}
