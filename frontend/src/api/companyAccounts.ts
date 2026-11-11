/**
 * 기업 조직·멤버·초대 (T124 화면). 계약: docs/enterprise/t122_openapi_proposal.yaml — **PROPOSED, docs/api/openapi.yaml 에 없음**.
 * 서버(T123)는 `COMPANY_ACCOUNTS_API=true` 일 때만 경로가 생기고(기본 꺼짐), DB 저장소가 없어 켜도 503 입니다.
 * 그래서 화면은 Mock 전용 플래그 뒤에 둡니다. 권한: 소속 아님 404, 같은 조직 역할 부족 403(T121).
 */
import type { HttpClient } from './http';

export type OrganizationStatus = 'pending' | 'active' | 'suspended' | 'closed' | 'rejected';
export type MemberRole = 'owner' | 'member';
export type InvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

export const ORG_STATUS_LABELS: Record<OrganizationStatus, string> = {
  pending: '운영 확인 대기', active: '활성', suspended: '정지', closed: '종료', rejected: '반려',
};
export const ROLE_LABELS: Record<MemberRole, string> = { owner: '기업 관리자', member: '기업 담당자' };
export const INVITATION_LABELS: Record<InvitationStatus, string> = {
  pending: '대기', accepted: '수락됨', revoked: '취소됨', expired: '만료',
};
export const MAX_RESENDS = 5;

export type Organization = {
  organization_id: string; name: string; status: OrganizationStatus; linked_company_id: string | null;
  status_reason: string | null; version: number; created_at: string;
};
export type MyOrganization = { organization: Organization; role: MemberRole };
export type Member = {
  user_id: string; display_name: string; email_masked: string; role: MemberRole; joined_at: string; version: number;
};
export type Invitation = {
  invitation_id: string; email_masked: string; role: MemberRole; status: InvitationStatus; expires_at: string;
  resend_count: number;
};

export interface CompanyAccountService {
  myOrganizations(signal?: AbortSignal): Promise<MyOrganization[]>;
  register(name: string): Promise<Organization>;
  organization(id: string, signal?: AbortSignal): Promise<Organization>;
  members(id: string, signal?: AbortSignal): Promise<Member[]>;
  changeRole(id: string, userId: string, role: MemberRole, version: number): Promise<Member>;
  removeMember(id: string, userId: string): Promise<void>;
  invitations(id: string, signal?: AbortSignal): Promise<Invitation[]>;
  invite(id: string, email: string, role: MemberRole): Promise<Invitation>;
  resend(id: string, invitationId: string): Promise<Invitation>;
  revoke(id: string, invitationId: string): Promise<void>;
  accept(token: string): Promise<MyOrganization>;
}

const org = (id: string) => `/v1/organizations/${encodeURIComponent(id)}`;

/** 실제 API 어댑터(준비만, 연결하지 않음 — T122 승인·migration 전). */
export function createHttpCompanyAccountService(http: HttpClient): CompanyAccountService {
  return {
    myOrganizations: (signal) => http.request('/v1/me/organizations', { signal }),
    register: (name) => http.request('/v1/organizations', { method: 'POST', body: { name } }),
    organization: (id, signal) => http.request(org(id), { signal }),
    members: (id, signal) => http.request(`${org(id)}/members`, { signal }),
    changeRole: (id, userId, role, version) =>
      http.request(`${org(id)}/members/${encodeURIComponent(userId)}`, { method: 'PATCH', body: { role, version } }),
    removeMember: (id, userId) => http.request(`${org(id)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
    invitations: (id, signal) => http.request(`${org(id)}/invitations`, { signal }),
    invite: (id, email, role) => http.request(`${org(id)}/invitations`, { method: 'POST', body: { email, role } }),
    resend: (id, inv) => http.request(`${org(id)}/invitations/${encodeURIComponent(inv)}/resend`, { method: 'POST' }),
    revoke: (id, inv) => http.request(`${org(id)}/invitations/${encodeURIComponent(inv)}`, { method: 'DELETE' }),
    accept: (token) => http.request('/v1/organization-invitations/accept', { method: 'POST', body: { token } }),
  };
}
