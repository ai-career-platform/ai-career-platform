import { useEffect, useState } from 'react';

export type ApiResource<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: T };

type Settled<T> = { key: string; attempt: number; outcome: { data: T } | { error: true } };

/**
 * 읽기 전용 API 한 건을 불러오는 훅.
 * - key 가 null 이면 호출하지 않습니다(idle).
 * - key·attempt 가 바뀌면 곧바로 loading 으로 보이고, 이전 key 의 늦은 응답은 버립니다.
 * - attempt 를 올리면 같은 key 를 다시 호출합니다(재시도).
 * fetcher 는 useCallback 으로 고정해서 넘겨 주세요.
 */
export function useApiResource<T>(
  key: string | null,
  attempt: number,
  fetcher: () => Promise<T>,
): ApiResource<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (key === null) return;
    let active = true;
    fetcher().then(
      (data) => { if (active) setSettled({ key, attempt, outcome: { data } }); },
      () => { if (active) setSettled({ key, attempt, outcome: { error: true } }); },
    );
    return () => { active = false; };
  }, [key, attempt, fetcher]);

  if (key === null) return { status: 'idle' };
  if (!settled || settled.key !== key || settled.attempt !== attempt) return { status: 'loading' };
  return 'data' in settled.outcome
    ? { status: 'ready', data: settled.outcome.data }
    : { status: 'error' };
}
