import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useQuery, type QueryKey } from './useQuery';

type Fn = (signal: AbortSignal) => Promise<string>;

describe('useQuery', () => {
  it('stays idle without a key and does not call fn', () => {
    const fn = vi.fn<Fn>();
    const { result } = renderHook(() => useQuery(null, fn));
    expect(result.current.status).toBe('idle');
    expect(fn).not.toHaveBeenCalled();
  });

  it('loads, then exposes data', async () => {
    const { result } = renderHook(() => useQuery(['a'], async () => 'A'));
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current).toMatchObject({ status: 'ready', data: 'A' }));
  });

  it('does not refetch when only fn identity changes', async () => {
    const fn = vi.fn<Fn>().mockResolvedValue('A');
    const { result, rerender } = renderHook(() => useQuery(['same'], (signal) => fn(signal)));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    rerender();
    rerender();
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('aborts the previous request and ignores its late answer when the key changes', async () => {
    const resolvers: Record<string, (value: string) => void> = {};
    const signals: Record<string, AbortSignal> = {};
    const { result, rerender } = renderHook(({ id }: { id: string }) => useQuery(['item', id], (signal) => {
      signals[id] = signal;
      return new Promise<string>((resolve) => { resolvers[id] = resolve; });
    }), { initialProps: { id: '1' } });

    rerender({ id: '2' });
    expect(signals['1']!.aborted).toBe(true);
    expect(result.current.status).toBe('loading');

    await act(async () => { resolvers['1']!('late-1'); });
    expect(result.current.status).toBe('loading');
    await act(async () => { resolvers['2']!('two'); });
    expect(result.current).toMatchObject({ status: 'ready', data: 'two' });
  });

  it('reports errors and retries with the same key', async () => {
    const fn = vi.fn<Fn>().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce('ok');
    const key: QueryKey = ['retry'];
    const { result } = renderHook(() => useQuery(key, fn));
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current).toMatchObject({ error: expect.objectContaining({ message: 'offline' }) });

    act(() => result.current.retry());
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current).toMatchObject({ status: 'ready', data: 'ok' }));
    expect(fn).toHaveBeenCalledTimes(2);
  });
});
