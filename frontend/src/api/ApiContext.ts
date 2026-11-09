import { createContext, useContext } from 'react';
import { createApi, type Api } from '.';
import { publicHttp } from './client';

/**
 * 화면이 쓰는 API 묶음. 기본값은 토큰 없는 공개 클라이언트이고,
 * AuthProvider 가 로그인 토큰·401 처리를 붙인 클라이언트로 바꿔 내려 줍니다.
 */
export const ApiContext = createContext<Api>(createApi(publicHttp));

export function useApi(): Api {
  return useContext(ApiContext);
}
