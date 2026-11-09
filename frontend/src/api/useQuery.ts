import { useCallback, useEffect, useRef, useState } from 'react';

export type QueryKey = readonly unknown[];

export type QueryState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: unknown }
  | { status: 'ready'; data: T };

export type Query<T> = QueryState<T> & {
  /** 같은 key 로 다시 불러옵니다. */
  retry: () => void;
  /**
   * 저장·삭제 응답으로 현재 key 의 데이터를 바로 바꿉니다(다시 불러오지 않음).
   * 아직 데이터가 없거나(idle·loading·error) key 가 바뀐 뒤면 아무것도 하지 않습니다.
   */
  setData: (update: (current: T) => T) => void;
};

type Settled<T> = { hash: string; attempt: number; outcome: { data: T } | { error: unknown } };

/**
 * 읽기 전용 API 한 건을 불러오는 훅. 모양은 TanStack Query 의 useQuery(key + 함수)와 같게 둡니다.
 * - key 가 null·false·undefined 면 호출하지 않습니다(idle). 의존 데이터가 준비됐을 때만 부르는 용도.
 * - key 가 바뀌면 곧바로 loading 으로 보이고, 이전 요청은 AbortSignal 로 취소하며 늦은 응답은 버립니다.
 * - fn 은 매 렌더 새로 만들어도 됩니다(useCallback 불필요). 다시 부르는 기준은 key 뿐입니다.
 */
export function useQuery<T>(
  key: QueryKey | null | false | undefined,
  fn: (signal: AbortSignal) => Promise<T>,
): Query<T> {
  const hash = key ? JSON.stringify(key) : null;
  const fnRef = useRef(fn);
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  // 아래 effect 보다 먼저 실행되어 항상 최신 fn 을 부릅니다.
  useEffect(() => { fnRef.current = fn; });

  useEffect(() => {
    if (hash === null) return;
    const controller = new AbortController();
    fnRef.current(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setSettled({ hash, attempt, outcome: { data } }); },
      (error: unknown) => { if (!controller.signal.aborted) setSettled({ hash, attempt, outcome: { error } }); },
    );
    return () => controller.abort();
  }, [hash, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const setData = useCallback((update: (current: T) => T) => {
    setSettled((previous) => (previous && previous.hash === hash && previous.attempt === attempt && 'data' in previous.outcome
      ? { ...previous, outcome: { data: update(previous.outcome.data) } }
      : previous));
  }, [hash, attempt]);

  if (hash === null) return { status: 'idle', retry, setData };
  if (!settled || settled.hash !== hash || settled.attempt !== attempt) return { status: 'loading', retry, setData };
  return 'data' in settled.outcome
    ? { status: 'ready', data: settled.outcome.data, retry, setData }
    : { status: 'error', error: settled.outcome.error, retry, setData };
}
