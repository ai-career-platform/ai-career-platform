import { publicHttp } from '../api/client';
import { useQuery } from '../api/useQuery';
import { googleApi } from './google';

/** 이 서버에서 Google 로그인을 쓸 수 있는지(GET /auth/gate: 404 = 꺼짐). 확인 전·오류면 false. */
export function useGoogleAvailable(): boolean {
  const query = useQuery(['google-available'], (signal) => googleApi(publicHttp).available(signal));
  return query.status === 'ready' && query.data;
}
