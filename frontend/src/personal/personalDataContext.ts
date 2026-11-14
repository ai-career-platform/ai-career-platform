import { createContext, useContext } from 'react';
import type { PersonalDataService } from '../api/personalData';

/** 로그인 사용자의 내 데이터 반출 서비스 (T143). Mock 모드면 Mock Adapter, 아니면 실제 API(T142). */
export const PersonalDataServiceContext = createContext<PersonalDataService | null>(null);

export function usePersonalDataService(): PersonalDataService {
  const service = useContext(PersonalDataServiceContext);
  if (!service) throw new Error('usePersonalDataService must be used inside <PersonalDataServiceProvider> after login');
  return service;
}
