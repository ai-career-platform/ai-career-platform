/**
 * 기업 공고 관리 (T127 화면). 계약: docs/enterprise/t125_posting_state_machine.json — **PROPOSED, openapi.yaml 에 없음**.
 * 서버(T126)는 `COMPANY_POSTINGS_API=true` 일 때만 경로가 생기고(기본 꺼짐), 저장소가 없어 켜도 503 입니다.
 * 기업은 게시할 수 없습니다 — 검수 요청까지만. 게시·반려·내림은 운영 관리자(T125 P-INV-1·2).
 */
import type { HttpClient } from './http';

export const POSTING_STATUSES = ['draft', 'pending_review', 'rejected', 'published', 'closed', 'expired', 'taken_down'] as const;
export type PostingStatus = (typeof POSTING_STATUSES)[number];
export const STATUS_LABELS: Record<PostingStatus, string> = {
  draft: '초안', pending_review: '검수 대기', rejected: '반려', published: '게시 중', closed: '마감', expired: '만료',
  taken_down: '운영 내림',
};
export const REASON_LABELS: Record<string, string> = {
  missing_required_info: '필수 정보 누락', discriminatory_requirement: '차별적 요건', personal_contact_info: '개인 연락처 게시',
  misleading_terms: '사실과 다른 조건', not_a_job_posting: '채용 공고가 아님', duplicate_posting: '중복 공고',
  unverified_link: '확인되지 않은 지원 링크', other: '기타', legal_request: '법적 요청', fraud_suspected: '사기 의심',
  organization_suspended: '조직 정지',
};
export const EMPLOYMENT_LABELS = { full_time: '정규직', contract: '계약직', intern: '인턴', part_time: '시간제' } as const;
export type EmploymentType = keyof typeof EMPLOYMENT_LABELS;
export const MAX_PUBLISH_DAYS = 60;

export type Posting = {
  posting_id: string; organization_id: string; status: PostingStatus; title: string; description: string | null;
  employment_type: EmploymentType | null; location_text: string | null; apply_url: string | null; expires_at: string | null;
  version: number; reason_code: string | null; reason_note: string | null; revision_of: string | null;
  public_posting_id: string | null; updated_at: string | null;
};
export type PostingFields = Partial<Pick<Posting, 'title' | 'description' | 'employment_type' | 'location_text' | 'apply_url' | 'expires_at'>>;

export interface CompanyPostingService {
  list(orgId: string, signal?: AbortSignal): Promise<Posting[]>;
  create(orgId: string, fields: PostingFields & { title: string }): Promise<Posting>;
  edit(orgId: string, postingId: string, fields: PostingFields, version: number): Promise<Posting>;
  submit(orgId: string, postingId: string, version: number): Promise<Posting>;
  withdraw(orgId: string, postingId: string, version: number): Promise<Posting>;
  close(orgId: string, postingId: string, version: number): Promise<Posting>;
  revise(orgId: string, postingId: string): Promise<Posting>;
}

const base = (orgId: string) => `/v1/organizations/${encodeURIComponent(orgId)}/postings`;

/** 실제 API 어댑터(준비만, 연결하지 않음 — T125 승인·migration 전). */
export function createHttpCompanyPostingService(http: HttpClient): CompanyPostingService {
  const act = (orgId: string, id: string, action: string, version: number) =>
    http.request<Posting>(`${base(orgId)}/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: { version } });
  return {
    list: (orgId, signal) => http.request<Posting[]>(base(orgId), { signal }),
    create: (orgId, fields) => http.request<Posting>(base(orgId), { method: 'POST', body: fields }),
    edit: (orgId, id, fields, version) =>
      http.request<Posting>(`${base(orgId)}/${encodeURIComponent(id)}`, { method: 'PATCH', body: { ...fields, version } }),
    submit: (orgId, id, version) => act(orgId, id, 'submit', version),
    withdraw: (orgId, id, version) => act(orgId, id, 'withdraw', version),
    close: (orgId, id, version) => act(orgId, id, 'close', version),
    revise: (orgId, id) => http.request<Posting>(`${base(orgId)}/${encodeURIComponent(id)}/revisions`, { method: 'POST' }),
  };
}
