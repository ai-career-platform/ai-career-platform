import { createContext, useContext } from 'react';
import type { CompanyAccountService } from '../api/companyAccounts';
import type { MockCompanyBackend } from '../mocks/companyAccounts';

/** 로그인 사용자에 묶인 기업 계정 서비스 (T124). 지금은 Mock Adapter 만 연결됩니다. */
export const CompanyServiceContext = createContext<CompanyAccountService | null>(null);
/** Mock 메일함(초대 링크) 표시용 — Mock 모드에서만 존재합니다. */
export const CompanyBackendContext = createContext<MockCompanyBackend | null>(null);

export function useCompanyService(): CompanyAccountService {
  const service = useContext(CompanyServiceContext);
  if (!service) throw new Error('useCompanyService must be used inside <CompanyServiceProvider> after login');
  return service;
}

export const useMockCompanyBackend = () => useContext(CompanyBackendContext);
