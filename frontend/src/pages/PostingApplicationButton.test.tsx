import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { PostingApplicationButton } from './PostingApplicationButton';

const ID = '55555555-5555-4555-8555-555555555555';
const fns = () => ({ login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>() });
const signedIn: AuthContextValue = {
  state: { status: 'authenticated', token: 't', user: { email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } }, ...fns(),
};
const anonymous: AuthContextValue = { state: { status: 'anonymous' }, ...fns() };

function renderButton(request: RequestFn, auth: AuthContextValue | null, enabled = true) {
  const tree = <WithApi request={request}><MemoryRouter><PostingApplicationButton postingId={ID} enabled={enabled} /></MemoryRouter></WithApi>;
  return render(auth ? <AuthContext.Provider value={auth}>{tree}</AuthContext.Provider> : tree);
}

describe('T103 add-to-applications on the posting detail', () => {
  it('creates a record with POST and links to the board', async () => {
    const request = vi.fn<RequestFn>(async () => ({ application_id: 'a1' }));
    renderButton(request, signedIn);
    fireEvent.click(screen.getByRole('button', { name: '지원 기록에 추가' }));
    expect(await screen.findByText(/지원 기록에 추가했습니다/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '지원 현황 보기' })).toHaveAttribute('href', '/me/applications');
    expect(screen.getByRole('button', { name: '지원 기록에 있음' })).toBeDisabled();
    expect(request).toHaveBeenCalledWith('/v1/me/job-applications',
      expect.objectContaining({ method: 'POST', body: { job_posting_id: ID } }));
  });

  it('treats 409 as "already recorded" without an error', async () => {
    renderButton(vi.fn<RequestFn>(async () => { throw new ApiError(409, '/v1/me/job-applications', undefined, 'CONFLICT'); }), signedIn);
    fireEvent.click(screen.getByRole('button', { name: '지원 기록에 추가' }));
    expect(await screen.findByText(/이미 지원 기록에 있는 공고입니다/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '지원 현황 보기' })).toBeInTheDocument();
  });

  it('explains other failures and lets the user retry', async () => {
    renderButton(vi.fn<RequestFn>(async () => { throw new ApiError(503, '/v1/me/job-applications'); }), signedIn);
    fireEvent.click(screen.getByRole('button', { name: '지원 기록에 추가' }));
    expect(await screen.findByText('추가하지 못했습니다. 잠시 후 다시 시도해 주세요.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '지원 기록에 추가' })).toBeEnabled();
  });

  it('renders nothing when the feature is off, signed out, or outside an AuthProvider', () => {
    for (const [auth, enabled] of [[signedIn, false], [anonymous, true], [null, true]] as const) {
      const request = vi.fn<RequestFn>();
      const { container, unmount } = renderButton(request, auth, enabled);
      expect(container).toBeEmptyDOMElement();
      expect(request).not.toHaveBeenCalled();
      unmount();
    }
  });
});
