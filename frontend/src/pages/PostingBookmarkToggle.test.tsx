import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { PostingBookmarkToggle } from './PostingBookmarkToggle';

const ID = '44444444-4444-4444-8444-444444444444';
const signedIn: AuthContextValue = {
  state: { status: 'authenticated', token: 't', user: { email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
};
const anonymous: AuthContextValue = { state: { status: 'anonymous' }, login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>() };

function renderToggle(request: RequestFn, auth: AuthContextValue | null, initial: boolean | null) {
  const tree = <WithApi request={request}><MemoryRouter><PostingBookmarkToggle postingId={ID} initial={initial} /></MemoryRouter></WithApi>;
  return render(auth ? <AuthContext.Provider value={auth}>{tree}</AuthContext.Provider> : tree);
}

describe('T40 bookmark toggle on the posting detail', () => {
  it('saves with PUT and then removes with DELETE, keeping the pressed state in sync', async () => {
    const request = vi.fn<RequestFn>(async () => undefined);
    renderToggle(request, signedIn, false);
    const save = screen.getByRole('button', { name: '관심 공고 저장' });
    expect(save).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(save);
    const unsave = await screen.findByRole('button', { name: '관심 공고 해제' });
    expect(unsave).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('관심 공고로 저장했습니다.');
    expect(request).toHaveBeenLastCalledWith(`/v1/me/bookmarks/${ID}`, expect.objectContaining({ method: 'PUT' }));
    fireEvent.click(unsave);
    expect(await screen.findByRole('button', { name: '관심 공고 저장' })).toHaveAttribute('aria-pressed', 'false');
    expect(request).toHaveBeenLastCalledWith(`/v1/me/bookmarks/${ID}`, expect.objectContaining({ method: 'DELETE' }));
  });

  it('starts from is_bookmarked=true', () => {
    renderToggle(vi.fn<RequestFn>(), signedIn, true);
    expect(screen.getByRole('button', { name: '관심 공고 해제' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps the previous state and explains when the request fails', async () => {
    renderToggle(vi.fn<RequestFn>(async () => { throw new Error('503'); }), signedIn, false);
    fireEvent.click(screen.getByRole('button', { name: '관심 공고 저장' }));
    expect(await screen.findByText('처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '관심 공고 저장' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows a login link instead of a button when signed out or outside an AuthProvider', () => {
    for (const auth of [anonymous, null]) {
      const { unmount } = renderToggle(vi.fn<RequestFn>(), auth, null);
      expect(screen.queryByRole('button')).toBeNull();
      expect(screen.getByRole('link', { name: '로그인' })).toHaveAttribute('href', '/login');
      unmount();
    }
  });
});
