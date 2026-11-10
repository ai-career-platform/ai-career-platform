/**
 * T85 운영 감사·AI 사용량 Mock Adapter — **합성 데이터만** 씁니다(실제 사용자 ID·이메일·토큰·문서 없음).
 * T84 서버 동작을 흉내 냅니다: 반열림 기간 [from, to), 최신 순, 조건에 묶인 cursor(다르면 400),
 * 형식 오류 422, KST 날짜 집계, 비용 상태 `unverified`. 네트워크 요청은 보내지 않습니다.
 * Mock 사용량 숫자는 가상의 값이며 실제 비용이 발생했다는 뜻이 아닙니다.
 */
import {
  ACTION_CODE_PATTERN, AUDIT_PATH, USAGE_PATH,
  type AdminAuditService, type AiUsageBucket, type AiUsageResult, type AuditEvent, type AuditEventPage,
  type AuditQuery, type UsageQuery,
} from '../api/adminAudit';
import { ApiError } from '../api/errors';

const sid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const HOUR = 3_600_000;

export type MockUsageRecord = {
  occurred_at: string;
  feature_code: 'document_analysis' | 'rag_answer' | 'agent';
  provider_model: string;
  input_tokens: number;
  output_tokens: number;
  /** 저장된 추정값(소수 6자리 문자열). 0 은 "무료"가 아니라 미기록일 수도 있음(T84 D2) */
  estimated_cost_usd: string;
  /** 사용자 ID 대신 상태만 둡니다. withdrawn = 탈퇴로 user_id 가 NULL 이 된 행 */
  user: 'active' | 'withdrawn';
};

const EVENT_KINDS: Array<Pick<AuditEvent, 'action_code' | 'resource_type'> & { actor: 'admin' | 'user' | 'system' }> = [
  { action_code: 'auth.login.success', resource_type: 'auth_session', actor: 'user' },
  { action_code: 'admin.role.grant', resource_type: 'user', actor: 'admin' },
  { action_code: 'admin.posting.close', resource_type: 'job_posting', actor: 'admin' },
  { action_code: 'document.file.download', resource_type: 'user_document', actor: 'admin' },
  { action_code: 'system.behavior.purge', resource_type: 'behavior_purge_run', actor: 'system' },
  { action_code: 'agent.tool.call', resource_type: 'agent_run', actor: 'user' },
  { action_code: 'ai.model.deploy', resource_type: 'model_version', actor: 'admin' },
];

/** 30건: 최근 7일에 흩어 놓고, 4건은 같은 시각(동률 정렬 확인용). */
export function seedAuditEvents(now: Date = new Date()): AuditEvent[] {
  const events: AuditEvent[] = [];
  for (let n = 1; n <= 30; n += 1) {
    const kind = EVENT_KINDS[n % EVENT_KINDS.length]!;
    const at = n <= 4 ? now.getTime() - 2 * HOUR : now.getTime() - n * 5 * HOUR;   // 모두 최근 7일 안
    events.push({
      audit_event_id: sid(100 + n),
      actor_user_id: kind.actor === 'system' ? null : sid(kind.actor === 'admin' ? 7 : 8),
      action_code: kind.action_code,
      resource_type: kind.resource_type,
      resource_id: sid(500 + n),
      request_id: `req-mock-${String(n).padStart(4, '0')}`,
      occurred_at: new Date(at).toISOString(),
    });
  }
  return events;
}

/** 여러 날짜·기능·모델, 0원(미검증) 행, 탈퇴 사용자 행을 포함한 가상 사용량. */
export function seedUsage(now: Date = new Date()): MockUsageRecord[] {
  const day = (offset: number, hourUtc: number) => {
    const d = new Date(now); d.setUTCHours(hourUtc, 0, 0, 0); d.setUTCDate(d.getUTCDate() - offset);
    return d.toISOString();
  };
  return [
    { occurred_at: day(1, 1), feature_code: 'document_analysis', provider_model: 'mock-model-a', input_tokens: 1200, output_tokens: 300, estimated_cost_usd: '0.012000', user: 'active' },
    { occurred_at: day(1, 14), feature_code: 'rag_answer', provider_model: 'mock-model-a', input_tokens: 800, output_tokens: 200, estimated_cost_usd: '0.008000', user: 'withdrawn' },
    { occurred_at: day(2, 3), feature_code: 'rag_answer', provider_model: 'mock-model-b', input_tokens: 2500, output_tokens: 700, estimated_cost_usd: '0.031500', user: 'active' },
    { occurred_at: day(3, 5), feature_code: 'agent', provider_model: 'mock-model-b', input_tokens: 4000, output_tokens: 900, estimated_cost_usd: '0.000000', user: 'active' },
    { occurred_at: day(3, 16), feature_code: 'agent', provider_model: 'mock-model-c', input_tokens: 600, output_tokens: 150, estimated_cost_usd: '0.002700', user: 'withdrawn' },
  ];
}

export type MockAdminAuditOptions = {
  now?: () => Date;
  latencyMs?: number;
  events?: AuditEvent[];
  usage?: MockUsageRecord[];
};

export type MockAdminAuditService = AdminAuditService & {
  calls: Array<{ method: 'listEvents' | 'getUsage'; query: AuditQuery | UsageQuery }>;
  /** 다음 호출 하나를 이 오류로 실패시킵니다 (테스트용). */
  failNext: (error: ApiError) => void;
};

const OFFSET = /(Z|[+-]\d{2}:\d{2})$/;
const invalid = (path: string) => new ApiError(422, path, undefined, 'VALIDATION_FAILED');
const KST_MS = 9 * HOUR;
const kstDate = (iso: string) => new Date(new Date(iso).getTime() + KST_MS).toISOString().slice(0, 10);
const microDollars = (value: string) => Math.round(Number(value) * 1_000_000);

function cursorHash(query: AuditQuery): string {
  return JSON.stringify([query.from, query.to, query.action_code ?? null]);
}

export function createMockAdminAuditService(options: MockAdminAuditOptions = {}): MockAdminAuditService {
  const now = options.now ?? (() => new Date());
  const events = options.events ?? seedAuditEvents(now());
  const usage = options.usage ?? seedUsage(now());
  const calls: MockAdminAuditService['calls'] = [];
  const failures: ApiError[] = [];

  async function respond<T>(method: 'listEvents' | 'getUsage', query: AuditQuery | UsageQuery, work: () => T,
    signal?: AbortSignal): Promise<T> {
    calls.push({ method, query: { ...query } });
    if (options.latencyMs) await new Promise((resolve) => setTimeout(resolve, options.latencyMs));
    if (signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
    const failure = failures.shift();
    if (failure) throw failure;
    return work();
  }

  function listEvents(query: AuditQuery, signal?: AbortSignal): Promise<AuditEventPage> {
    return respond('listEvents', query, () => {
      if (!OFFSET.test(query.from) || !OFFSET.test(query.to)) throw invalid(AUDIT_PATH);
      const from = Date.parse(query.from); const to = Date.parse(query.to);
      if (Number.isNaN(from) || Number.isNaN(to) || from >= to) throw invalid(AUDIT_PATH);
      if (query.action_code && !ACTION_CODE_PATTERN.test(query.action_code)) throw invalid(AUDIT_PATH);
      const limit = query.limit ?? 20;
      if (limit < 1 || limit > 100) throw invalid(AUDIT_PATH);
      let offset = 0;
      if (query.cursor) {
        try {
          const decoded = JSON.parse(atob(query.cursor)) as { o: number; h: string };
          if (decoded.h !== cursorHash(query) || !Number.isInteger(decoded.o)) throw new Error('mismatch');
          offset = decoded.o;
        } catch {
          throw new ApiError(400, AUDIT_PATH, undefined, 'INVALID_CURSOR');
        }
      }
      const matched = events
        .filter((e) => Date.parse(e.occurred_at) >= from && Date.parse(e.occurred_at) < to)
        .filter((e) => !query.action_code || e.action_code === query.action_code)
        .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.audit_event_id.localeCompare(a.audit_event_id));
      const items = matched.slice(offset, offset + limit);
      const next = offset + limit < matched.length ? btoa(JSON.stringify({ o: offset + limit, h: cursorHash(query) })) : null;
      return { items: items.map((e) => ({ ...e })), next_cursor: next };
    }, signal);
  }

  function getUsage(query: UsageQuery, signal?: AbortSignal): Promise<AiUsageResult> {
    return respond('getUsage', query, () => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(query.from) || !/^\d{4}-\d{2}-\d{2}$/.test(query.to) || query.from > query.to) {
        throw invalid(USAGE_PATH);
      }
      const groups = new Map<string, { requests: number; input: number; output: number; micro: number }>();
      for (const r of usage) {
        const day = kstDate(r.occurred_at);
        if (day < query.from || day > query.to) continue;
        const key = query.group_by === 'day' ? day : r[query.group_by];
        const g = groups.get(key) ?? { requests: 0, input: 0, output: 0, micro: 0 };
        g.requests += 1; g.input += r.input_tokens; g.output += r.output_tokens; g.micro += microDollars(r.estimated_cost_usd);
        groups.set(key, g);
      }
      const buckets: AiUsageBucket[] = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, g]) => ({
        key, request_count: g.requests, input_tokens: g.input, output_tokens: g.output, estimated_cost_usd: g.micro / 1_000_000,
      }));
      return { buckets, costStatus: 'unverified', source: 'mock' };
    }, signal);
  }

  return { listEvents, getUsage, calls, failNext: (error) => { failures.push(error); } };
}
