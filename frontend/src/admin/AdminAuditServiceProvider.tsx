import { useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import type { AdminAuditService } from '../api/adminAudit';
import { useApi } from '../api/ApiContext';
import { env } from '../config/env';
import { createMockAdminAuditService } from '../mocks/adminAudit';
import { AdminAuditServiceContext } from './adminAuditContext';

/**
 * 운영 감사·AI 사용량 화면의 데이터 경로 (T85).
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Adapter (합성 데이터, 네트워크 없음)
 * - 그 외: 로그인 세션의 HttpClient 로 T84 API 를 부릅니다(useApi().adminAudit). 서버가 admin 역할·권한을 다시 검사합니다.
 * 이 Provider 는 env.adminAuditUi 플래그가 켜졌을 때만 라우트에 들어갑니다(기본 꺼짐).
 */
export function AdminAuditServiceProvider({ service, children }: { service?: AdminAuditService; children?: ReactNode }) {
  const api = useApi();
  const [mock] = useState(() => (env.mockEnabled ? createMockAdminAuditService({ latencyMs: 250 }) : null));
  return (
    <AdminAuditServiceContext.Provider value={service ?? mock ?? api.adminAudit}>
      {children ?? <Outlet />}
    </AdminAuditServiceContext.Provider>
  );
}
