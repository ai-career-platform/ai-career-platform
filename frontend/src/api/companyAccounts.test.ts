/** T124 기업 계정 HTTP 어댑터: 경로·메서드·본문이 서버 계약(T123, backend/app/routers/company_accounts.py)과 같은지 확인합니다. */
import { describe, expect, it, vi } from 'vitest';
import { apiFrom, type RequestFn } from '../test/api';

describe('createHttpCompanyAccountService', () => {
  it('maps each call to the T123 endpoint', async () => {
    const request = vi.fn<RequestFn>(async () => ({}));
    const service = apiFrom(request).companyAccounts;
    await service.myOrganizations();
    await service.register('합성 기업');
    await service.organization('o/1');
    await service.members('o-1');
    await service.changeRole('o-1', 'u/2', 'owner', 3);
    await service.removeMember('o-1', 'u-2');
    await service.invitations('o-1');
    await service.invite('o-1', 'new@example.invalid', 'member');
    await service.resend('o-1', 'i/9');
    await service.revoke('o-1', 'i-9');
    await service.accept('tok');
    expect(request.mock.calls.map(([path, init]) => [init?.method ?? 'GET', path])).toEqual([
      ['GET', '/v1/me/organizations'],
      ['POST', '/v1/organizations'],
      ['GET', '/v1/organizations/o%2F1'],
      ['GET', '/v1/organizations/o-1/members'],
      ['PATCH', '/v1/organizations/o-1/members/u%2F2'],
      ['DELETE', '/v1/organizations/o-1/members/u-2'],
      ['GET', '/v1/organizations/o-1/invitations'],
      ['POST', '/v1/organizations/o-1/invitations'],
      ['POST', '/v1/organizations/o-1/invitations/i%2F9/resend'],
      ['DELETE', '/v1/organizations/o-1/invitations/i-9'],
      ['POST', '/v1/organization-invitations/accept'],
    ]);
    // 서버 모델(extra="forbid"): OrganizationCreate·MemberUpdate·InvitationCreate·InvitationAccept 필드 그대로
    expect(request.mock.calls[1]![1]).toMatchObject({ body: { name: '합성 기업' } });
    expect(request.mock.calls[4]![1]).toMatchObject({ body: { role: 'owner', version: 3 } });
    expect(request.mock.calls[7]![1]).toMatchObject({ body: { email: 'new@example.invalid', role: 'member' } });
    expect(request.mock.calls[10]![1]).toMatchObject({ body: { token: 'tok' } });
    // 본문이 없는 호출은 본문을 보내지 않는다
    for (const i of [5, 8, 9]) expect(request.mock.calls[i]![1]?.body).toBeUndefined();
  });
});
