import { createContext, useContext } from 'react';
import type { AdminAuditService } from '../api/adminAudit';

/** 운영 감사·AI 사용량 화면이 쓰는 서비스 (T85). 지금은 Mock Adapter 만 연결됩니다. */
export const AdminAuditServiceContext = createContext<AdminAuditService | null>(null);

export function useAdminAuditService(): AdminAuditService {
  const service = useContext(AdminAuditServiceContext);
  if (!service) throw new Error('useAdminAuditService must be used inside <AdminAuditServiceProvider>');
  return service;
}
