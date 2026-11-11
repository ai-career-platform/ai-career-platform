/**
 * T156 크롤러 관리자 Mock Adapter — **합성 데이터만** 씁니다(실제 공고·URL·HTML 없음). 네트워크 요청 없음.
 * T155 서버 규칙을 흉내 냅니다.
 * - 검색어 이름 중복(NFKC·대소문자 무시, 삭제 포함) → 409 KEYWORD_EXISTS
 * - 실행: 진행 중 Job 이 있으면 ACTIVE_JOB_EXISTS, 비활성은 KEYWORD_DISABLED. 같은 멱등 키는 같은 결과(replayed)
 * - 중단: PENDING 만. 재시도: FAILED·CANCELLED 만. 스케줄은 시간만 바꿀 수 있고 활성화는 거부
 */
import {
  COMMAND_REASON_HEADER, normalizeKeywordInput,
  type CommandRecord, type CommandResult, type CrawlerAdminService, type CrawlerJob, type CrawlerKeyword,
  type CrawlerRun, type CrawlerSchedule, type JobStatus, type KeywordAuditEntry, type RunEvent,
} from '../api/crawlerAdmin';
import { ApiError } from '../api/errors';

type MockKeyword = CrawlerKeyword & { deleted: boolean; discovered: number };
export type CrawlerAdminMockOptions = {
  latencyMs?: number;
  now?: () => Date;
  /** false 면 서버 쓰기 API 꺼짐(404)을 흉내 냅니다. */
  writeApi?: boolean;
  /** 지정하면 모든 호출이 이 상태 코드로 실패합니다(403 권한 회수, 503 등 화면 확인용). */
  failWith?: number;
};

const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const HOUR = 3_600_000;
const SEED = ['AI', 'Python', '데이터 분석', 'LLM', '업무 자동화', 'AI 엔지니어'];

export function createMockCrawlerAdminService(options: CrawlerAdminMockOptions = {}): CrawlerAdminService & {
  /** 테스트용: 현재 상태 보기 */
  snapshot: () => { keywords: MockKeyword[]; jobs: CrawlerJob[]; commands: CommandRecord[]; audit: KeywordAuditEntry[] };
} {
  const now = options.now ?? (() => new Date());
  const latency = options.latencyMs ?? 0;
  const writeApi = options.writeApi ?? true;
  const t0 = now().getTime();
  const iso = (ms: number) => new Date(ms).toISOString();

  let nextKeyword = 1;
  let nextAudit = 1;
  let nextJob = 100;
  let nextCommand = 900;
  const keywords: MockKeyword[] = SEED.map((keyword, i) => ({
    keyword_id: nextKeyword++, keyword, enabled: true, priority: i + 1, deleted: false, discovered: [5, 4, 6, 3, 2, 8][i]!,
    created_at: iso(t0 - 72 * HOUR), updated_at: iso(t0 - 72 * HOUR),
  }));
  const job = (keyword_id: number, status: JobStatus, hoursAgo: number, error_code: string | null = null): CrawlerJob => ({
    job_id: uuid(nextJob++), keyword_id, status, created_at: iso(t0 - hoursAgo * HOUR),
    started_at: status === 'PENDING' ? null : iso(t0 - hoursAgo * HOUR + 60_000),
    ended_at: ['FAILED', 'COMPLETED', 'CANCELLED'].includes(status) ? iso(t0 - hoursAgo * HOUR + 300_000) : null,
    error_code, attempt_count: status === 'PENDING' ? null : 1, attempt_state: status === 'COMPLETED' ? 'COMPLETED' : null,
  });
  const jobs: CrawlerJob[] = [
    job(1, 'COMPLETED', 30), job(2, 'COMPLETED', 29), job(3, 'FAILED', 28, 'FIXTURE_PARSE_INVALID'),
    job(4, 'COMPLETED', 27), job(6, 'PENDING', 1),
  ];
  const runs: CrawlerRun[] = [
    { run_id: uuid(501), schedule_id: 'jobkorea-daily', trigger: 'scheduled', mode: 'fixture', scheduled_for: iso(t0 - 30 * HOUR),
      attempt: 1, status: 'SUCCEEDED', started_at: iso(t0 - 30 * HOUR), ended_at: iso(t0 - 29.9 * HOUR),
      fetched_count: 14, inserted_count: 12, updated_count: 0, duplicate_count: 2, failed_count: 0, error_code: null },
    { run_id: uuid(502), schedule_id: 'jobkorea-daily', trigger: 'retry', mode: 'fixture', scheduled_for: iso(t0 - 28 * HOUR),
      attempt: 2, status: 'FAILED', started_at: iso(t0 - 28 * HOUR), ended_at: iso(t0 - 27.9 * HOUR),
      fetched_count: 3, inserted_count: 0, updated_count: 0, duplicate_count: 1, failed_count: 2, error_code: 'FIXTURE_PARSE_INVALID' },
  ];
  const events: RunEvent[] = [
    { event_id: 1, run_id: uuid(501), occurred_at: iso(t0 - 30 * HOUR), level: 'INFO', event_type: 'RUN_STARTED', safe_message: '합성 Fixture 실행 시작' },
    { event_id: 2, run_id: uuid(501), occurred_at: iso(t0 - 29.9 * HOUR), level: 'INFO', event_type: 'RUN_SUCCEEDED', safe_message: '신규 12 · 중복 2' },
    { event_id: 3, run_id: uuid(502), occurred_at: iso(t0 - 28 * HOUR), level: 'WARNING', event_type: 'PARSE_INVALID', safe_message: '검증 실패 2건 격리' },
    { event_id: 4, run_id: uuid(502), occurred_at: iso(t0 - 27.9 * HOUR), level: 'ERROR', event_type: 'RUN_FAILED', safe_message: '재시도 한도 도달' },
  ];
  const schedules: CrawlerSchedule[] = [{
    schedule_id: 'jobkorea-daily', source_id: 'jobkorea', enabled: false, timezone: 'Asia/Seoul', local_time: '03:00',
    mode: 'fixture', next_run_at: iso(t0 + 15 * HOUR), last_run_at: iso(t0 - 30 * HOUR),
  }];
  const commands: CommandRecord[] = [];
  const audit: KeywordAuditEntry[] = [];
  const ledger = new Map<string, { signature: string; result: CommandResult }>();

  const wait = async <T>(value: () => T): Promise<T> => {
    if (latency) await new Promise((r) => setTimeout(r, latency));
    if (options.failWith) throw new ApiError(options.failWith, '/v1/admin/crawler (mock)');
    return value();
  };
  const fail = (status: number, reason?: string): never => {
    const headers = new Headers(reason ? { [COMMAND_REASON_HEADER]: reason } : {});
    throw new ApiError(status, '/v1/admin/crawler (mock)', undefined, status === 409 ? 'CONFLICT' : undefined,
      undefined, undefined, headers);
  };
  const writable = () => { if (!writeApi) fail(404); };
  const live = (id: number) => keywords.find((k) => k.keyword_id === id && !k.deleted);
  const publicKeyword = ({ deleted: _d, discovered: _x, ...k }: MockKeyword): CrawlerKeyword => k;
  const snap = (k: MockKeyword) => ({ keyword: k.keyword, enabled: k.enabled, priority: k.priority, deleted: k.deleted });
  const record = (k: MockKeyword, action: KeywordAuditEntry['action'], before: Record<string, unknown> | null) => {
    audit.unshift({ audit_id: nextAudit++, keyword_id: k.keyword_id, actor: 'admin:mock', action,
      before_state: before, after_state: snap(k), occurred_at: now().toISOString() });
  };
  const validate = (keyword: string, priority: number) => {
    const display = normalizeKeywordInput(keyword);
    if (!display || display.length > 100 || !Number.isInteger(priority) || priority < 1 || priority > 9999) fail(422);
    return display;
  };
  const taken = (display: string, except?: number) =>
    keywords.some((k) => k.keyword_id !== except && k.keyword.toLocaleLowerCase() === display.toLocaleLowerCase());

  function execute(type: CommandResult['command_type'], target: string, signature: string, key: string,
    effect: () => [CommandResult['outcome'], string, Record<string, unknown>]): CommandResult {
    writable();
    if (!/^[A-Za-z0-9._:-]{1,200}$/.test(key)) fail(422);
    const prior = ledger.get(key);
    if (prior) {
      if (prior.signature !== signature) fail(409, 'IDEMPOTENCY_KEY_REUSED');
      if (prior.result.outcome === 'REFUSED') fail(409, prior.result.reason);
      return { ...prior.result, replayed: true };
    }
    const [outcome, reason, result] = effect();
    const res: CommandResult = { command_id: uuid(nextCommand++), command_type: type, target, outcome, reason, result, replayed: false };
    ledger.set(key, { signature, result: res });
    commands.unshift({ ...res, actor: 'admin:mock', created_at: now().toISOString() });
    if (outcome === 'REFUSED') fail(409, reason);
    return res;
  }

  function enqueue(keywordId: number): [CommandResult['outcome'], string, Record<string, unknown>] {
    const k = live(keywordId);
    if (!k) return ['REFUSED', 'KEYWORD_NOT_FOUND', {}];
    if (!k.enabled) return ['REFUSED', 'KEYWORD_DISABLED', {}];
    if (jobs.some((j) => j.keyword_id === keywordId && ['PENDING', 'RUNNING', 'FETCHED'].includes(j.status))) {
      return ['REFUSED', 'ACTIVE_JOB_EXISTS', {}];
    }
    const created = { ...job(keywordId, 'PENDING', 0), created_at: now().toISOString() };
    jobs.unshift(created);
    return ['ACCEPTED', 'FIXTURE_JOB_PENDING', { job_id: created.job_id, keyword_id: keywordId, status: 'PENDING', mode: 'fixture' }];
  }

  return {
    snapshot: () => ({ keywords: [...keywords], jobs: [...jobs], commands: [...commands], audit: [...audit] }),
    listKeywordStats: () => wait(() => keywords.filter((k) => !k.deleted)
      .sort((a, b) => a.priority - b.priority || a.keyword_id - b.keyword_id)
      .map((k) => ({ keyword_id: k.keyword_id, keyword: k.keyword, enabled: k.enabled, priority: k.priority,
        job_count: jobs.filter((j) => j.keyword_id === k.keyword_id).length, discovered_posting_count: k.discovered }))),
    listJobs: ({ status, keyword_id }) => wait(() => jobs.filter((j) =>
      (!status || j.status === status) && (!keyword_id || j.keyword_id === keyword_id))),
    listRuns: () => wait(() => [...runs]),
    listRunEvents: (runId) => wait(() => events.filter((e) => e.run_id === runId).sort((a, b) => b.event_id - a.event_id)),
    getSettings: () => wait(() => ({
      schedules: schedules.map((s) => ({ ...s })),
      night_window: writeApi ? { timezone: 'Asia/Seoul', start: '21:00', end: '08:00', slot_minutes: 30, max_slots: 22, editable: false } : null,
      live_collection: 'HOLD' as const, writeApi,
    })),
    listCommands: () => wait(() => { writable(); return [...commands]; }),
    keywordAudit: (keywordId) => wait(() => { writable(); return audit.filter((a) => a.keyword_id === keywordId); }),
    createKeyword: ({ keyword, priority }) => wait(() => {
      writable();
      const display = validate(keyword, priority);
      if (taken(display)) fail(409, 'KEYWORD_EXISTS');
      const k: MockKeyword = { keyword_id: nextKeyword++, keyword: display, enabled: true, priority, deleted: false, discovered: 0,
        created_at: now().toISOString(), updated_at: now().toISOString() };
      keywords.push(k);
      record(k, 'CREATE', null);
      return publicKeyword(k);
    }),
    updateKeyword: (keywordId, { keyword, priority }) => wait(() => {
      writable();
      const display = validate(keyword, priority);
      const k = live(keywordId) ?? fail(404);
      if (taken(display, keywordId)) fail(409, 'KEYWORD_EXISTS');
      const before = snap(k);
      Object.assign(k, { keyword: display, priority, updated_at: now().toISOString() });
      record(k, 'EDIT', before);
      return publicKeyword(k);
    }),
    setKeywordEnabled: (keywordId, enabled) => wait(() => {
      writable();
      const k = live(keywordId) ?? fail(404);
      const before = snap(k);
      k.enabled = enabled;
      record(k, 'SET_ENABLED', before);
      return publicKeyword(k);
    }),
    deleteKeyword: (keywordId) => wait(() => {
      writable();
      const k = live(keywordId) ?? fail(404);
      const before = snap(k);
      Object.assign(k, { deleted: true, enabled: false });
      record(k, 'SOFT_DELETE', before);
    }),
    runKeyword: (keywordId, key) => wait(() =>
      execute('RUN', `keyword:${keywordId}`, `run:${keywordId}:fixture`, key, () => enqueue(keywordId))),
    stopJob: (jobId, key) => wait(() => execute('STOP', `job:${jobId}`, `stop:${jobId}`, key, () => {
      const j = jobs.find((x) => x.job_id === jobId);
      if (!j) return ['REFUSED', 'JOB_NOT_FOUND', {}];
      if (j.status !== 'PENDING') {
        return ['REFUSED', ['FAILED', 'COMPLETED', 'CANCELLED'].includes(j.status) ? 'JOB_ALREADY_FINISHED' : 'RUNNING_JOB_STOP_UNSUPPORTED', { status: j.status }];
      }
      Object.assign(j, { status: 'CANCELLED', ended_at: now().toISOString() });
      return ['ACCEPTED', 'JOB_CANCELLED', { job_id: jobId, status: 'CANCELLED' }];
    })),
    retryJob: (jobId, key) => wait(() => execute('RETRY', `job:${jobId}`, `retry:${jobId}`, key, () => {
      const j = jobs.find((x) => x.job_id === jobId);
      if (!j) return ['REFUSED', 'JOB_NOT_FOUND', {}];
      if (!['FAILED', 'CANCELLED'].includes(j.status)) return ['REFUSED', 'JOB_NOT_RETRYABLE', { status: j.status }];
      const [outcome, reason, result] = enqueue(j.keyword_id);
      return [outcome, reason, outcome === 'ACCEPTED' ? { ...result, retry_of: jobId } : result];
    })),
    updateScheduleTime: (scheduleId, localTime, key) => wait(() =>
      execute('SCHEDULE_UPDATE', `schedule:${scheduleId}`, `schedule:${scheduleId}:${localTime}`, key, () => {
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(localTime)) fail(422);
        const s = schedules.find((x) => x.schedule_id === scheduleId);
        if (!s) return ['REFUSED', 'SCHEDULE_NOT_FOUND', {}];
        if (s.enabled || s.mode !== 'fixture') return ['REFUSED', 'ACTIVE_SCHEDULE_CHANGE_REQUIRES_APPROVAL', {}];
        const before = s.local_time.slice(0, 5);
        if (before === localTime) return ['ACCEPTED', 'NO_CHANGE', { schedule_id: scheduleId, local_time: before }];
        s.local_time = localTime;
        return ['ACCEPTED', 'SCHEDULE_TIME_UPDATED', { schedule_id: scheduleId, local_time_before: before, local_time: localTime }];
      })),
  };
}
