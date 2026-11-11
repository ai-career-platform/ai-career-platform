import { createContext, useContext } from 'react';
import type { NotificationService } from '../api/notifications';

/** 로그인한 사용자에 묶인 알림 서비스 (T97). 지금은 Mock Adapter 만 연결됩니다. */
export const NotificationServiceContext = createContext<NotificationService | null>(null);

export function useNotificationService(): NotificationService {
  const service = useContext(NotificationServiceContext);
  if (!service) throw new Error('useNotificationService must be used inside <NotificationServiceProvider> after login');
  return service;
}
