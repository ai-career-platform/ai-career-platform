import { createContext, useContext } from 'react';
import type { JobApplicationService } from '../api/jobApplications';

/** 로그인 사용자에 묶인 지원 현황 서비스 (T103). 지금은 Mock Adapter 만 연결됩니다. */
export const ApplicationServiceContext = createContext<JobApplicationService | null>(null);

export function useApplicationService(): JobApplicationService {
  const service = useContext(ApplicationServiceContext);
  if (!service) throw new Error('useApplicationService must be used inside <ApplicationServiceProvider> after login');
  return service;
}
