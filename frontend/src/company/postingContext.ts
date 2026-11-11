import { createContext, useContext } from 'react';
import type { CompanyPostingService } from '../api/companyPostings';
import type { MockPostingBackend } from '../mocks/companyPostings';

/** 로그인 사용자의 기업 공고 서비스 (T127). 지금은 Mock Adapter 만 연결됩니다. */
export const PostingServiceContext = createContext<CompanyPostingService | null>(null);
export const PostingBackendContext = createContext<MockPostingBackend | null>(null);

export function usePostingService(): CompanyPostingService {
  const service = useContext(PostingServiceContext);
  if (!service) throw new Error('usePostingService must be used inside <PostingServiceProvider> after login');
  return service;
}
