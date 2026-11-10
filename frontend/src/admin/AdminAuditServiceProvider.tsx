import { useState, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import type { AdminAuditService } from '../api/adminAudit';
import { createMockAdminAuditService } from '../mocks/adminAudit';
import { AdminAuditServiceContext } from './adminAuditContext';

/**
 * 운영 감사·AI 사용량 화면의 데이터 경로 (T85).
 * - 지금: 메모리 Mock Adapter (네트워크 요청 없음). 이 Provider 는 env.adminAuditUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - 운영 연결(T60·T84 정책 이후): createHttpAdminAuditService(useApi 의 HttpClient)로 바꾸는 곳이 여기 한 곳입니다.
 */
export function AdminAuditServiceProvider({ service, children }: { service?: AdminAuditService; children?: ReactNode }) {
  const [fallback] = useState(() => createMockAdminAuditService({ latencyMs: 250 }));
  return (
    <AdminAuditServiceContext.Provider value={service ?? fallback}>
      {children ?? <Outlet />}
    </AdminAuditServiceContext.Provider>
  );
}
