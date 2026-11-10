import { createContext, useContext } from 'react';
import type { ModerationService } from '../api/moderation';

/** 검수 화면이 쓰는 서비스. 지금은 Mock Adapter만 연결됩니다 (ModerationServiceProvider). */
export const ModerationServiceContext = createContext<ModerationService | null>(null);

export function useModerationService(): ModerationService {
  const service = useContext(ModerationServiceContext);
  if (!service) throw new Error('useModerationService must be used inside <ModerationServiceProvider>');
  return service;
}
