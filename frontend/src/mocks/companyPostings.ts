/**
 * T127 기업 공고 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음. T126 서버 규칙을 흉내 냅니다.
 * - 소속·권한은 기업 Mock(T124)의 현재 상태로 판단: 소속 아님 404, 검증 전 조직의 검수 요청 403.
 * - 상태 기계(T125): 초안→검수 대기→(운영)게시|반려, 반려 수정→초안, 게시→마감, 게시 중 수정은 수정본.
 * - version 이 다르면 409, 필수 항목 없으면 422, 지원 링크는 https 만. 기업은 게시할 수 없음.
 * - review(): 운영 관리자 결정을 흉내 내는 시험·개발용 함수(화면에는 없음).
 */
import { ApiError } from '../api/errors';
import {
  MAX_PUBLISH_DAYS, type CompanyPostingService, type Posting, type PostingFields, type PostingStatus,
} from '../api/companyPostings';
import type { MockCompanyBackend } from './companyAccounts';

const DAY = 86_400_000;
const PATH = '/v1/organizations/postings';
const EDITABLE = ['title', 'description', 'employment_type', 'location_text', 'apply_url', 'expires_at'] as const;
const REQUIRED = ['title', 'description', 'employment_type', 'location_text', 'expires_at'] as const;
const TRANSITIONS: Record<string, PostingStatus[]> = {
  draft: ['pending_review'], pending_review: ['draft', 'published', 'rejected'], rejected: ['draft'],
  published: ['closed', 'expired', 'taken_down'],
};

export type MockPostingOptions = { now?: () => Date; latencyMs?: number; seed?: boolean };
type Failure = 'load' | 'mutate';

export function createMockPostingBackend(company: MockCompanyBackend, options: MockPostingOptions = {}) {
  const now = options.now ?? (() => new Date());
  const rows: Posting[] = [];
  let seq = 0;
  let failures: Failure[] = [];
  const iso = (days: number) => new Date(now().getTime() + days * DAY).toISOString();
  const newId = () => `00000000-0000-4000-8301-${String(++seq).padStart(12, '0')}`;
  const blank = (orgId: string, status: PostingStatus, title: string, extra: Partial<Posting> = {}): Posting => ({
    posting_id: newId(), organization_id: orgId, status, title, description: '합성 직무 설명 (가상)', employment_type: 'full_time',
    location_text: '서울', apply_url: 'https://careers.example.invalid/apply', expires_at: iso(30), version: 1, reason_code: null,
    reason_note: null, revision_of: null, public_posting_id: null, updated_at: iso(-seq), ...extra,
  });

  if (options.seed !== false) {
    const org = company.snapshot().orgs.find((o) => o.name === '가상테크 (Mock)');
    if (org) {
      rows.push(blank(org.organization_id, 'draft', '데이터 엔지니어 (초안, 가상)', { description: null }));
      rows.push(blank(org.organization_id, 'pending_review', '프론트엔드 개발자 (가상)'));
      rows.push(blank(org.organization_id, 'rejected', 'QA 엔지니어 (가상)', { reason_code: 'personal_contact_info',
        reason_note: '담당자 개인 휴대전화 번호를 지우고 회사 채용 메일로 바꿔 주세요.' }));
      rows.push(blank(org.organization_id, 'published', '백엔드 개발자 (가상)', { public_posting_id: 'pub-1' }));
      rows.push(blank(org.organization_id, 'expired', '모바일 개발자 (가상)', { expires_at: iso(-1) }));
    }
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
  const invalid = () => err(422, 'VALIDATION_FAILED', '입력값을 확인해 주세요.');

  /** 기업 Mock 상태로 소속·조직 상태 확인. 소속 아님·종료 → 404 */
  function orgScope(orgId: string, userId: string) {
    const snap = company.snapshot();
    const org = snap.orgs.find((o) => o.organization_id === orgId);
    const member = snap.members.find((m) => m.organization_id === orgId && m.user_id === userId);
    if (!org || !member || org.status === 'closed' || org.status === 'rejected') throw notFound();
    return org;
  }
  const find = (orgId: string, id: string) => {
    const row = rows.find((r) => r.posting_id === id && r.organization_id === orgId);
    if (!row) throw notFound();
    return row;
  };
  const expire = () => {
    for (const r of rows) if (r.status === 'published' && r.expires_at && new Date(r.expires_at) <= now()) r.status = 'expired';
  };
  function move(row: Posting, to: PostingStatus, version: number | null, extra: Partial<Posting> = {}) {
    if (!(TRANSITIONS[row.status] ?? []).includes(to)) throw conflict();
    if (version !== null && row.version !== version) throw conflict();
    Object.assign(row, { status: to, version: row.version + 1, updated_at: now().toISOString(), ...extra });
    return structuredClone(row);
  }
  function validate(fields: PostingFields) {
    if (fields.apply_url && !/^https:\/\/\S+$/.test(fields.apply_url)) throw invalid();
    if (fields.title !== undefined && !fields.title?.trim()) throw invalid();
  }
  const pick = (fields: PostingFields) => Object.fromEntries(EDITABLE.filter((k) => k in fields).map((k) => [k, fields[k] ?? null]));

  return {
    failNext(...kinds: Failure[]) { failures = [...failures, ...kinds]; },
    rows: () => structuredClone(rows),
    /** 운영 관리자 결정 흉내(시험·개발용). 게시 시 만료가 60일 이내여야 함 */
    review(postingId: string, decision: 'approve' | 'reject', reasonCode?: string, note?: string) {
      const row = rows.find((r) => r.posting_id === postingId)!;
      if (decision === 'reject') return move(row, 'rejected', null, { reason_code: reasonCode ?? 'other', reason_note: note ?? null });
      if (!row.expires_at || new Date(row.expires_at).getTime() > now().getTime() + MAX_PUBLISH_DAYS * DAY) throw invalid();
      if (row.revision_of) {
        const original = rows.find((r) => r.posting_id === row.revision_of)!;
        Object.assign(original, pick(row), { version: original.version + 1, updated_at: now().toISOString() });
        move(row, 'published', null);
        Object.assign(row, { status: 'closed', reason_note: '원 공고에 반영됨' });
        return structuredClone(row);
      }
      return move(row, 'published', null, { public_posting_id: `pub-${row.posting_id.slice(-4)}` });
    },
    serviceFor(userId: string): CompanyPostingService {
      return {
        async list(orgId, signal) {
          await wait(signal); maybeFail('load');
          orgScope(orgId, userId); expire();
          return structuredClone(rows.filter((r) => r.organization_id === orgId))
            .sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''));
        },
        async create(orgId, fields) {
          await wait(); maybeFail('mutate');
          orgScope(orgId, userId); validate(fields);
          const row = blank(orgId, 'draft', fields.title.trim(), { description: null, employment_type: null, location_text: null,
            apply_url: null, expires_at: null, updated_at: now().toISOString(), ...pick(fields) });
          rows.push(row);
          return structuredClone(row);
        },
        async edit(orgId, id, fields, version) {
          await wait(); maybeFail('mutate');
          orgScope(orgId, userId); validate(fields);
          const row = find(orgId, id);
          if (row.version !== version) throw conflict();
          if (row.status === 'rejected') move(row, 'draft', version, { reason_code: null, reason_note: null });
          else if (row.status === 'draft') row.version += 1;
          else throw conflict();
          Object.assign(row, pick(fields), { updated_at: now().toISOString() });
          return structuredClone(row);
        },
        async submit(orgId, id, version) {
          await wait(); maybeFail('mutate');
          const org = orgScope(orgId, userId);
          if (org.status !== 'active') throw forbidden();
          const row = find(orgId, id);
          if (REQUIRED.some((k) => !row[k])) throw invalid();
          return move(row, 'pending_review', version);
        },
        async withdraw(orgId, id, version) {
          await wait(); maybeFail('mutate');
          orgScope(orgId, userId);
          return move(find(orgId, id), 'draft', version);
        },
        async close(orgId, id, version) {
          await wait(); maybeFail('mutate');
          orgScope(orgId, userId);
          return move(find(orgId, id), 'closed', version);
        },
        async revise(orgId, id) {
          await wait(); maybeFail('mutate');
          orgScope(orgId, userId);
          const original = find(orgId, id);
          if (original.status !== 'published') throw conflict();
          if (rows.some((r) => r.revision_of === id && ['draft', 'pending_review', 'rejected'].includes(r.status))) throw conflict();
          const row = blank(orgId, 'draft', original.title, { ...pick(original), revision_of: id, updated_at: now().toISOString() });
          rows.push(row);
          return structuredClone(row);
        },
      };
    },
  };
}

export type MockPostingBackend = ReturnType<typeof createMockPostingBackend>;
