import { useMemo, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import { useApi } from '../api/ApiContext';
import type { ModerationService } from '../api/moderation';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { createMockModerationService } from '../mocks/moderation';
import { ModerationServiceContext } from './moderationContext';

/**
 * 검수 화면의 데이터 경로를 고릅니다. 이 Provider 는 env.adminModerationUi(기본 꺼짐)일 때만 라우트에 들어갑니다.
 * - Mock 모드(VITE_API_MOCK=true): 메모리 Mock Adapter (네트워크 요청 없음).
 * - 그 밖: 실제 API(T81 `/v1/admin/moderation-cases`, 서버 ADMIN_MODERATION_API·migration 0010 필요) — api.moderation.
 */
export function ModerationServiceProvider({ service, children }: { service?: ModerationService; children?: ReactNode }) {
  const { state } = useAuth();
  const api = useApi();
  const viewerId = state.status === 'authenticated' ? state.user.userId : undefined;
  // Mock 모드에서만 메모리 저장소를 만듭니다. 로그인 사용자가 바뀌면 새로 만듭니다(서버의 토큰 해석을 흉내 냄).
  const fallback = useMemo(
    () => (env.mockEnabled ? createMockModerationService({ viewer: () => viewerId, latencyMs: 300 }) : api.moderation),
    [viewerId, api],
  );
  return (
    <ModerationServiceContext.Provider value={service ?? fallback}>
      {children ?? <Outlet />}
    </ModerationServiceContext.Provider>
  );
}
