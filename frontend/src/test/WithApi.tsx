import type { ReactNode } from 'react';
import { ApiContext } from '../api/ApiContext';
import { apiFrom, type RequestFn } from './api';

/** 화면 테스트에서 useApi() 가 받을 API 를 가짜 전송으로 바꿉니다. */
export function WithApi({ request, children }: { request: RequestFn; children: ReactNode }) {
  return <ApiContext.Provider value={apiFrom(request)}>{children}</ApiContext.Provider>;
}
