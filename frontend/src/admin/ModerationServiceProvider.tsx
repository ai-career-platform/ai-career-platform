import { useMemo, type ReactNode } from 'react';
import { Outlet } from 'react-router';
import type { ModerationService } from '../api/moderation';
import { useAuth } from '../auth/useAuth';
import { createMockModerationService } from '../mocks/moderation';
import { ModerationServiceContext } from './moderationContext';

/**
 * 검수 화면의 데이터 경로를 고릅니다.
 * - 지금: 메모리 Mock Adapter (네트워크 요청 없음). 이 Provider는 env.adminModerationUi(= Mock 모드 + 플래그)일 때만 라우트에 들어갑니다.
 * - T81 이후: createHttpModerationService(useApi 의 HttpClient)로 바꾸는 곳이 여기 한 곳입니다.
 */
export function ModerationServiceProvider({ service, children }: { service?: ModerationService; children?: ReactNode }) {
  const { state } = useAuth();
  const viewerId = state.status === 'authenticated' ? state.user.userId : undefined;
  // 로그인 사용자가 바뀌면 Mock 저장소도 새로 만듭니다(서버의 토큰 해석을 흉내 냄).
  const fallback = useMemo(() => createMockModerationService({ viewer: () => viewerId, latencyMs: 300 }), [viewerId]);
  return (
    <ModerationServiceContext.Provider value={service ?? fallback}>
      {children ?? <Outlet />}
    </ModerationServiceContext.Provider>
  );
}
