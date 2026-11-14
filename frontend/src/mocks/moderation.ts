/**
 * T82 검수 Mock Adapter — 네트워크 없이 메모리에서만 동작합니다. 실제 DB·API와 연결하지 않습니다.
 * 데이터는 모두 합성 값입니다(@example.invalid, 가상 제목). Mock 성공은 실제 서비스 PASS가 아닙니다.
 *
 * 서버(T81 backend/app/services/moderation.py)가 할 판단을 흉내 냅니다(담당 해제 T04·T05 포함): 401·403·404·409(APPROVAL_CLOSED/CONFLICT)·422, version 낙관적 잠금,
 * 자기 콘텐츠 검수 금지, 담당자만 결정, 재검토에서 최초 결정자 차단 (T80 상태 모델 T02·T06·T07·T09).
 */
import { ApiError } from '../api/errors';
import {
  availableActions, rejectInputError,
  type Decision, type ModerationCaseDetail, type ModerationCaseEvent, type ModerationCaseSummary,
  type ModerationService, type ModerationStatus,
} from '../api/moderation';

/** Mock 로그인 관리자(mocks/handlers.ts admin@example.com)의 user_id 와 같습니다. */
export const MOCK_ADMIN_ID = 'admin@example.com';
/** 합성 관리자·사용자 (로그인 계정 아님) */
export const OTHER_ADMIN_ID = 'reviewer-b@example.invalid';
export const THIRD_ADMIN_ID = 'reviewer-c@example.invalid';
const OWNER_ID = 'owner-1@example.invalid';
const MOCK_ADMINS = new Set([MOCK_ADMIN_ID, OTHER_ADMIN_ID, THIRD_ADMIN_ID]);

const at = (iso: string) => new Date(iso).toISOString();

function seedEvent(caseId: string, n: number, event: ModerationCaseEvent['event'], from: ModerationStatus | null,
  to: ModerationStatus, actor: string | null, when: string, reason: string | null = null): ModerationCaseEvent {
  return { event_id: `${caseId}-e${n}`, event, from_status: from, to_status: to, actor_user_id: actor, reason_code: reason,
    occurred_at: at(when) };
}

type SeedCase = Omit<ModerationCaseDetail, 'events'> & { events?: ModerationCaseEvent[] };

function base(id: string, partial: Partial<SeedCase>): ModerationCaseDetail {
  const created = partial.created_at ?? '2026-11-09T01:00:00Z';
  const detail: ModerationCaseDetail = {
    case_id: id, target_type: 'job_posting', target_id: `00000000-0000-4000-8000-0000000${id.slice(-5)}`,
    target_summary: '합성 채용공고', trigger: 'REPORT', status: 'PENDING', priority: 2, assignee_id: null,
    due_at: '2026-11-12T09:00:00Z', flags: [], report_count: 0, version: 1, content_owner_id: OWNER_ID,
    submitted_by: null, first_decider_id: null, decided_by: null, decided_at: null, reason_code: null, appeal_count: 0,
    close_reason: null, created_at: created, events: [], ...partial,
  };
  if (detail.events.length === 0) detail.events = [seedEvent(id, 1, 'SUBMIT', null, 'PENDING', null, created)];
  return detail;
}

/** 상태·경계 조건을 고루 담은 합성 검수 건 */
export function seedModerationCases(): ModerationCaseDetail[] {
  return [
    base('mc-00001', { target_summary: '[합성] 백엔드 신입 채용공고 — 연락처 노출 신고', priority: 1, report_count: 3,
      flags: ['PII_PATTERN'], due_at: '2026-11-10T03:00:00Z' }),
    base('mc-00002', { target_type: 'shared_document', trigger: 'PRE_PUBLISH', priority: 3,
      target_summary: '[합성] 이력서 작성 가이드 (공용 자료)', content_owner_id: MOCK_ADMIN_ID, submitted_by: MOCK_ADMIN_ID,
      due_at: '2026-11-13T09:00:00Z' }),
    base('mc-00003', { status: 'IN_REVIEW', assignee_id: MOCK_ADMIN_ID, version: 2, target_summary: '[합성] 데이터 분석가 채용공고',
      trigger: 'PRE_PUBLISH', priority: 3, flags: ['DUPLICATE_SUSPECT'],
      events: [seedEvent('mc-00003', 1, 'SUBMIT', null, 'PENDING', null, '2026-11-09T01:00:00Z'),
        seedEvent('mc-00003', 2, 'ASSIGN', 'PENDING', 'IN_REVIEW', MOCK_ADMIN_ID, '2026-11-09T02:00:00Z')] }),
    base('mc-00004', { status: 'IN_REVIEW', assignee_id: OTHER_ADMIN_ID, version: 2, target_summary: '[합성] 프론트엔드 경력 채용공고',
      events: [seedEvent('mc-00004', 1, 'SUBMIT', null, 'PENDING', null, '2026-11-09T01:00:00Z'),
        seedEvent('mc-00004', 2, 'ASSIGN', 'PENDING', 'IN_REVIEW', OTHER_ADMIN_ID, '2026-11-09T03:00:00Z')] }),
    base('mc-00005', { status: 'APPEALED', appeal_count: 1, first_decider_id: MOCK_ADMIN_ID, decided_by: MOCK_ADMIN_ID,
      decided_at: at('2026-11-08T05:00:00Z'), reason_code: 'INACCURATE', version: 4, target_type: 'document_analysis',
      target_summary: '[합성] AI 문서 분석 결과 신고 건', events: [
        seedEvent('mc-00005', 1, 'SUBMIT', null, 'PENDING', null, '2026-11-08T01:00:00Z'),
        seedEvent('mc-00005', 2, 'ASSIGN', 'PENDING', 'IN_REVIEW', MOCK_ADMIN_ID, '2026-11-08T02:00:00Z'),
        seedEvent('mc-00005', 3, 'REJECT', 'IN_REVIEW', 'REJECTED', MOCK_ADMIN_ID, '2026-11-08T05:00:00Z', 'INACCURATE'),
        seedEvent('mc-00005', 4, 'APPEAL', 'REJECTED', 'APPEALED', OWNER_ID, '2026-11-09T05:00:00Z')] }),
    base('mc-00006', { status: 'APPEALED', appeal_count: 1, first_decider_id: OTHER_ADMIN_ID, decided_by: OTHER_ADMIN_ID,
      decided_at: at('2026-11-08T06:00:00Z'), reason_code: 'RIGHTS_UNCLEAR', version: 4, target_type: 'company',
      target_summary: '[합성] 가상기업 주식회사 소개', events: [
        seedEvent('mc-00006', 1, 'SUBMIT', null, 'PENDING', null, '2026-11-08T01:00:00Z'),
        seedEvent('mc-00006', 2, 'ASSIGN', 'PENDING', 'IN_REVIEW', OTHER_ADMIN_ID, '2026-11-08T02:00:00Z'),
        seedEvent('mc-00006', 3, 'REJECT', 'IN_REVIEW', 'REJECTED', OTHER_ADMIN_ID, '2026-11-08T06:00:00Z', 'RIGHTS_UNCLEAR'),
        seedEvent('mc-00006', 4, 'APPEAL', 'REJECTED', 'APPEALED', OWNER_ID, '2026-11-09T06:00:00Z')] }),
    base('mc-00007', { status: 'APPROVED', first_decider_id: OTHER_ADMIN_ID, decided_by: OTHER_ADMIN_ID, version: 3,
      decided_at: at('2026-11-07T04:00:00Z'), trigger: 'PRE_PUBLISH', priority: 3, target_summary: '[합성] 인턴 채용공고' }),
    base('mc-00008', { status: 'REJECTED', first_decider_id: THIRD_ADMIN_ID, decided_by: THIRD_ADMIN_ID, version: 3,
      decided_at: at('2026-11-07T05:00:00Z'), reason_code: 'HARMFUL', target_type: 'retrieval_run',
      target_summary: '[합성] AI 질의응답 결과 신고 건', events: [
        seedEvent('mc-00008', 1, 'SUBMIT', null, 'PENDING', null, '2026-11-07T01:00:00Z'),
        seedEvent('mc-00008', 2, 'ASSIGN', 'PENDING', 'IN_REVIEW', THIRD_ADMIN_ID, '2026-11-07T02:00:00Z'),
        seedEvent('mc-00008', 3, 'REJECT', 'IN_REVIEW', 'REJECTED', THIRD_ADMIN_ID, '2026-11-07T05:00:00Z', 'HARMFUL')] }),
    base('mc-00009', { status: 'CLOSED', close_reason: 'TARGET_DELETED', version: 2, target_summary: '[합성] 삭제된 채용공고',
      events: [seedEvent('mc-00009', 1, 'SUBMIT', null, 'PENDING', null, '2026-11-06T01:00:00Z'),
        seedEvent('mc-00009', 2, 'CLOSE', 'PENDING', 'CLOSED', null, '2026-11-06T09:00:00Z', 'TARGET_DELETED')] }),
  ];
}

export interface MockModerationOptions {
  /** 현재 로그인한 관리자 user_id (서버의 토큰 해석을 대신함) */
  viewer: () => string | null | undefined;
  cases?: ModerationCaseDetail[];
  /** 응답 지연(ms). 개발 화면에서 로딩 상태를 보려고 둡니다. 기본 0 */
  latencyMs?: number;
  now?: () => Date;
}

export type MockModerationService = ModerationService & {
  /** 테스트용: 다음 n번 호출을 이 오류로 실패시킵니다. */
  failNext: (error: ApiError, times?: number) => void;
  /** 테스트용: 서버에서 다른 관리자가 먼저 바꾼 상황을 만듭니다 (version 증가). */
  touch: (caseId: string, change?: Partial<ModerationCaseDetail>) => void;
  calls: { method: string; caseId?: string }[];
};

const clone = <T,>(value: T): T => structuredClone(value);
const summary = ({ events: _events, content_owner_id: _o, submitted_by: _s, first_decider_id: _f, decided_by: _d,
  decided_at: _da, reason_code: _r, appeal_count: _a, close_reason: _c, created_at: _ca, ...rest }: ModerationCaseDetail,
): ModerationCaseSummary => rest;

export function createMockModerationService(options: MockModerationOptions): MockModerationService {
  const store = new Map((options.cases ?? seedModerationCases()).map((c) => [c.case_id, clone(c)]));
  const now = options.now ?? (() => new Date());
  const failures: ApiError[] = [];
  const calls: MockModerationService['calls'] = [];
  let sequence = 0;

  async function respond<T>(method: string, caseId: string | undefined, work: () => T, signal?: AbortSignal): Promise<T> {
    calls.push({ method, caseId });
    if (options.latencyMs) await new Promise((resolve) => setTimeout(resolve, options.latencyMs));
    if (signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
    const failure = failures.shift();
    if (failure) throw failure;
    return clone(work());
  }

  function viewerAdmin(): string {
    const viewer = options.viewer();
    if (!viewer) throw new ApiError(401, '/v1/admin/moderation-cases', undefined, 'UNAUTHENTICATED');
    if (!MOCK_ADMINS.has(viewer)) throw new ApiError(403, '/v1/admin/moderation-cases', undefined, 'FORBIDDEN');
    return viewer;
  }

  function load(caseId: string): ModerationCaseDetail {
    const found = store.get(caseId);
    if (!found) throw new ApiError(404, `/v1/admin/moderation-cases/${caseId}`, undefined, 'NOT_FOUND');
    return found;
  }

  function transition(c: ModerationCaseDetail, version: number, kind: 'assign' | 'decide' | 'release', viewer: string) {
    if (c.status === 'APPROVED' || c.status === 'REJECTED' || c.status === 'CLOSED') {
      throw new ApiError(409, c.case_id, undefined, 'APPROVAL_CLOSED');
    }
    if (version !== c.version) throw new ApiError(409, c.case_id, undefined, 'CONFLICT');
    const allowed = availableActions(c, viewer)[kind];
    if (!allowed.allowed) {
      const conflict = ((kind === 'decide' || kind === 'release') && c.status !== 'IN_REVIEW')
        || (kind === 'assign' && c.status === 'IN_REVIEW');
      throw new ApiError(conflict ? 409 : 403, c.case_id, undefined, conflict ? 'CONFLICT' : 'FORBIDDEN');
    }
  }

  function record(c: ModerationCaseDetail, event: ModerationCaseEvent['event'], to: ModerationStatus, actor: string,
    reason: string | null = null) {
    sequence += 1;
    c.events.push({ event_id: `${c.case_id}-m${sequence}`, event, from_status: c.status, to_status: to, actor_user_id: actor,
      reason_code: reason, occurred_at: now().toISOString() });
    c.status = to;
    c.version += 1;
  }

  return {
    calls,
    failNext(error, times = 1) { for (let i = 0; i < times; i += 1) failures.push(error); },
    touch(caseId, change = {}) {
      const c = load(caseId);
      Object.assign(c, change);
      c.version += 1;
    },
    list(query, signal) {
      return respond('list', undefined, () => {
        viewerAdmin();
        const items = [...store.values()]
          .filter((c) => (!query.status || c.status === query.status)
            && (!query.target_type || c.target_type === query.target_type)
            && (!query.priority || c.priority === query.priority))
          .sort((a, b) => a.priority - b.priority || a.due_at.localeCompare(b.due_at))
          .map(summary);
        return { items, next_cursor: null };
      }, signal);
    },
    get(caseId, signal) {
      return respond('get', caseId, () => { viewerAdmin(); return load(caseId); }, signal);
    },
    assign(caseId, { version }) {
      return respond('assign', caseId, () => {
        const viewer = viewerAdmin();
        const c = load(caseId);
        transition(c, version, 'assign', viewer);
        c.assignee_id = viewer;
        record(c, 'ASSIGN', 'IN_REVIEW', viewer);
        return c;
      });
    },
    release(caseId, { version }) {
      return respond('release', caseId, () => {
        const viewer = viewerAdmin();
        const c = load(caseId);
        transition(c, version, 'release', viewer);
        c.assignee_id = null;
        if (c.appeal_count === 1) record(c, 'RELEASE_APPEAL', 'APPEALED', viewer);
        else record(c, 'RELEASE', 'PENDING', viewer);
        return c;
      });
    },
    decide(caseId, body: { version: number } & Decision) {
      return respond('decide', caseId, () => {
        const viewer = viewerAdmin();
        const c = load(caseId);
        if (body.decision === 'REJECT' && rejectInputError(body.reason_code, body.note ?? '')) {
          throw new ApiError(422, caseId, undefined, 'VALIDATION_FAILED');
        }
        transition(c, body.version, 'decide', viewer);
        c.first_decider_id ??= viewer;
        c.decided_by = viewer;
        c.decided_at = now().toISOString();
        c.assignee_id = null;
        if (body.decision === 'APPROVE') {
          record(c, 'APPROVE', 'APPROVED', viewer);
        } else {
          c.reason_code = body.reason_code;
          record(c, 'REJECT', 'REJECTED', viewer, body.reason_code);
        }
        return c;
      });
    },
  };
}
