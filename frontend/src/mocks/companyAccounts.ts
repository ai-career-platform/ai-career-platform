/**
 * T124 기업 콘솔 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음. T123 서버 규칙을 흉내 냅니다.
 * - 소속이 아니면 404, 같은 조직에서 역할이 부족하면 403, 검증 전 조직의 초대는 403.
 * - 마지막 관리자 강등·제외·탈퇴, 중복 초대, 이미 멤버, 재전송 한도, 오래된 version 은 409(`CONFLICT` 하나).
 * - 초대 TTL 72시간, 재전송 시 토큰 교체(이전 토큰 무효). 수락은 로그인 이메일 = 초대 이메일일 때만, 실패는 모두 404.
 * - 초대 링크는 `#token=`(fragment). Mock 메일함(mailbox)으로만 전달 — 실제 메일 없음.
 * 사용자 ID 는 Mock 로그인과 같이 이메일입니다(src/mocks/handlers.ts).
 */
import { ApiError } from '../api/errors';
import {
  MAX_RESENDS, type CompanyAccountService, type Invitation, type Member, type MemberRole, type MyOrganization,
  type Organization,
} from '../api/companyAccounts';

const HOUR = 3_600_000;
const PATH = '/v1/organizations';

type MemberRow = Member & { organization_id: string; email: string };
type InviteRow = Invitation & { organization_id: string; email: string; token: string };

export type MockCompanyOptions = { now?: () => Date; latencyMs?: number; seed?: boolean };
type Failure = 'load' | 'mutate';

const mask = (email: string) => `${email.slice(0, 1)}***@${email.split('@')[1] ?? '?'}`;
const nameOf = (email: string) => (email === 'admin@example.com' ? '운영 관리자' : email === 'user@example.com' ? '일반 사용자' : email);

export function createMockCompanyBackend(options: MockCompanyOptions = {}) {
  const now = options.now ?? (() => new Date());
  const orgs = new Map<string, Organization>();
  const members: MemberRow[] = [];
  const invites: InviteRow[] = [];
  const mailbox: { to: string; link: string }[] = [];
  let seq = 0;
  let failures: Failure[] = [];
  const id = (prefix: string) => `00000000-0000-4000-8${prefix}-${String(++seq).padStart(12, '0')}`;
  const token = () => `mock${Array.from({ length: 4 }, () => Math.random().toString(36).slice(2, 12)).join('')}`.padEnd(40, 'x');

  function addMember(orgId: string, email: string, role: MemberRole, displayName = nameOf(email)) {
    members.push({ organization_id: orgId, user_id: email, email, display_name: displayName, email_masked: mask(email), role,
      joined_at: new Date(now().getTime() - (10 - members.length) * HOUR).toISOString(), version: 1 });
  }
  function addOrg(name: string, status: Organization['status'], owner: string): Organization {
    const row: Organization = { organization_id: id('101'), name, status, linked_company_id: null, status_reason: null,
      version: 1, created_at: new Date(now().getTime() - (20 - seq) * HOUR).toISOString() };
    orgs.set(row.organization_id, row);
    addMember(row.organization_id, owner, 'owner');
    return row;
  }
  function addInvite(orgId: string, email: string, role: MemberRole, expiresInHours: number, resendCount = 0): InviteRow {
    const row: InviteRow = { invitation_id: id('201'), organization_id: orgId, email, email_masked: mask(email), role,
      status: 'pending', token: token(), expires_at: new Date(now().getTime() + expiresInHours * HOUR).toISOString(),
      resend_count: resendCount };
    invites.push(row);
    return row;
  }

  if (options.seed !== false) {
    const main = addOrg('가상테크 (Mock)', 'active', 'user@example.com');
    addMember(main.organization_id, 'staff.a@example.invalid', 'member', '가상 담당자 A');
    addInvite(main.organization_id, 'pending@example.invalid', 'member', 48);
    addInvite(main.organization_id, 'late@example.invalid', 'member', -1, 2);
    const other = addOrg('예시소프트 (Mock)', 'active', 'boss@example.invalid');
    const boss = members.at(-1);
    if (boss) boss.display_name = '가상 관리자';
    addMember(other.organization_id, 'user@example.com', 'member');
    addOrg('검증대기랩 (Mock)', 'pending', 'user@example.com');
  }

  const wait = (signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, options.latencyMs ?? 0);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
  });
  function maybeFail(kind: Failure) {
    if (failures[0] !== kind) return;
    failures = failures.slice(1);
    throw new ApiError(0, PATH);
  }
  const err = (status: number, code: string, message: string) => new ApiError(status, PATH, undefined, code, message);
  const notFound = () => err(404, 'NOT_FOUND', '요청한 정보를 찾을 수 없습니다.');
  const forbidden = () => err(403, 'FORBIDDEN', '접근 권한이 없습니다.');
  const conflict = () => err(409, 'CONFLICT', '현재 상태에서는 처리할 수 없습니다.');
  const expire = () => {
    for (const inv of invites) if (inv.status === 'pending' && new Date(inv.expires_at) <= now()) inv.status = 'expired';
  };
  const memberOf = (orgId: string, userId: string) => members.find((m) => m.organization_id === orgId && m.user_id === userId);
  const owners = (orgId: string) => members.filter((m) => m.organization_id === orgId && m.role === 'owner').length;
  const toInvitation = ({ invitation_id, email_masked, role, status, expires_at, resend_count }: InviteRow): Invitation =>
    ({ invitation_id, email_masked, role, status, expires_at, resend_count });
  const toMember = ({ user_id, display_name, email_masked, role, joined_at, version }: MemberRow): Member =>
    ({ user_id, display_name, email_masked, role, joined_at, version });

  /** 소속 아님·종료·반려 → 404. ownerOnly: 담당자면 403. activeOnly: 검증 전·정지 조직이면 403 */
  function scope(orgId: string, userId: string, ownerOnly = false, activeOnly = false) {
    const row = orgs.get(orgId);
    const me = memberOf(orgId, userId);
    if (!row || !me || row.status === 'closed' || row.status === 'rejected') throw notFound();
    if (ownerOnly && me.role !== 'owner') throw forbidden();
    if (activeOnly && row.status !== 'active') throw forbidden();
    return row;
  }

  return {
    failNext(...kinds: Failure[]) { failures = [...failures, ...kinds]; },
    mailbox,
    lastInviteLink: () => mailbox.at(-1)?.link ?? null,
    /** 운영 관리자 승인 흉내(T123 /admin/organizations/{id}/verification) */
    approve(orgId: string) { const row = orgs.get(orgId); if (row) Object.assign(row, { status: 'active', version: row.version + 1 }); },
    snapshot: () => structuredClone({ orgs: [...orgs.values()], members, invites }),
    serviceFor(userId: string): CompanyAccountService {
      return {
        async myOrganizations(signal) {
          await wait(signal); maybeFail('load');
          return members.filter((m) => m.user_id === userId)
            .map((m): MyOrganization => ({ organization: structuredClone(orgs.get(m.organization_id)!), role: m.role }))
            .filter((x) => !['closed', 'rejected'].includes(x.organization.status))
            .sort((a, b) => a.organization.created_at.localeCompare(b.organization.created_at));
        },
        async register(name) {
          await wait(); maybeFail('mutate');
          if (!name.trim() || name.length > 200) throw err(422, 'VALIDATION_FAILED', '입력값을 확인해 주세요.');
          return structuredClone(addOrg(name.trim(), 'pending', userId));
        },
        async organization(orgId, signal) {
          await wait(signal); maybeFail('load');
          return structuredClone(scope(orgId, userId));
        },
        async members(orgId, signal) {
          await wait(signal); maybeFail('load');
          scope(orgId, userId);
          return members.filter((m) => m.organization_id === orgId).map(toMember);
        },
        async changeRole(orgId, target, role, version) {
          await wait(); maybeFail('mutate');
          scope(orgId, userId, true);
          const row = memberOf(orgId, target);
          if (!row) throw notFound();
          if (row.version !== version) throw conflict();
          if (row.role === 'owner' && role !== 'owner' && owners(orgId) <= 1) throw conflict();
          Object.assign(row, { role, version: row.version + 1 });
          return toMember(row);
        },
        async removeMember(orgId, target) {
          await wait(); maybeFail('mutate');
          scope(orgId, userId, target !== userId);
          const index = members.findIndex((m) => m.organization_id === orgId && m.user_id === target);
          const row = members[index];
          if (index < 0 || !row) throw notFound();
          if (row.role === 'owner' && owners(orgId) <= 1) throw conflict();
          members.splice(index, 1);
        },
        async invitations(orgId, signal) {
          await wait(signal); maybeFail('load');
          scope(orgId, userId, true);
          expire();
          return invites.filter((i) => i.organization_id === orgId).map(toInvitation);
        },
        async invite(orgId, email, role) {
          await wait(); maybeFail('mutate');
          scope(orgId, userId, true, true);
          expire();
          const address = email.trim().toLowerCase();
          if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(address)) throw err(422, 'VALIDATION_FAILED', '입력값을 확인해 주세요.');
          if (invites.some((i) => i.organization_id === orgId && i.email === address && i.status === 'pending')) throw conflict();
          if (members.some((m) => m.organization_id === orgId && m.email === address)) throw conflict();
          const row = addInvite(orgId, address, role, 72);
          mailbox.push({ to: address, link: `/company-invitations/accept#token=${row.token}` });
          return toInvitation(row);
        },
        async resend(orgId, invitationId) {
          await wait(); maybeFail('mutate');
          scope(orgId, userId, true, true);
          expire();
          const row = invites.find((i) => i.invitation_id === invitationId && i.organization_id === orgId);
          if (!row) throw notFound();
          if (row.status !== 'pending' || row.resend_count >= MAX_RESENDS) throw conflict();
          Object.assign(row, { token: token(), resend_count: row.resend_count + 1,
            expires_at: new Date(now().getTime() + 72 * HOUR).toISOString() });
          mailbox.push({ to: row.email, link: `/company-invitations/accept#token=${row.token}` });
          return toInvitation(row);
        },
        async revoke(orgId, invitationId) {
          await wait(); maybeFail('mutate');
          scope(orgId, userId, true);
          const row = invites.find((i) => i.invitation_id === invitationId && i.organization_id === orgId);
          if (!row) throw notFound();
          if (row.status !== 'pending') throw conflict();
          row.status = 'revoked';
        },
        async accept(tokenValue) {
          await wait(); maybeFail('mutate');
          expire();
          const row = invites.find((i) => i.token === tokenValue);
          const target = row ? orgs.get(row.organization_id) : undefined;
          if (!row || !target || row.status !== 'pending' || row.email !== userId.toLowerCase() || target.status !== 'active') {
            throw notFound();
          }
          if (memberOf(row.organization_id, userId)) throw conflict();
          addMember(row.organization_id, userId, row.role);
          row.status = 'accepted';
          return { organization: structuredClone(target), role: row.role };
        },
      };
    },
  };
}

export type MockCompanyBackend = ReturnType<typeof createMockCompanyBackend>;
