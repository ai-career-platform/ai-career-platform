/**
 * T156 크롤러 관리자 콘솔 — 계약 타입·서비스 인터페이스·오류 문구.
 *
 * 서버 계약
 * - 읽기(T155 #124, main): GET /api/v1/admin/crawler/{keywords,jobs,schedules,runs,runs/:id/events,stats/keywords}
 * - 쓰기(T155 #233, 플래그 CRAWLER_ADMIN_WRITE_API 기본 꺼짐): 검색어 CRUD·감사, /settings, /schedules/:id,
 *   /commands/{run,stop,retry}, /commands
 * 모든 경로는 admin 역할만 쓸 수 있습니다. 응답에는 Raw HTML·대상 URL·승인 정보가 없습니다.
 * 실제 사이트 수집(LIVE)은 HOLD 이며 이 화면은 LIVE 실행 버튼을 두지 않습니다.
 */
import { ApiError } from './errors';

export const CRAWLER_ADMIN_BASE = '/v1/admin/crawler';
export const COMMAND_REASON_HEADER = 'X-Crawler-Command-Reason';
export const JOB_STATUSES = ['PENDING', 'RUNNING', 'FETCHED', 'FAILED', 'COMPLETED', 'CANCELLED'] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export type KeywordStat = {
  keyword_id: number;
  keyword: string;
  enabled: boolean;
  priority: number;
  job_count: number;
  discovered_posting_count: number;
};

export type CrawlerKeyword = {
  keyword_id: number;
  keyword: string;
  enabled: boolean;
  priority: number;
  created_at?: string;
  updated_at?: string;
};

export type CrawlerJob = {
  job_id: string;
  keyword_id: number;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  error_code: string | null;
  attempt_count: number | null;
  attempt_state: string | null;
};

export type CrawlerRun = {
  run_id: string;
  schedule_id: string;
  trigger: string;
  mode: 'fixture' | 'live';
  scheduled_for: string;
  attempt: number;
  status: 'RUNNING' | 'SUCCEEDED' | 'PARTIAL' | 'FAILED' | 'CANCELLED';
  started_at: string;
  ended_at: string | null;
  fetched_count: number | null;
  inserted_count: number | null;
  updated_count: number | null;
  duplicate_count: number | null;
  failed_count: number | null;
  error_code: string | null;
};

export type RunEvent = {
  event_id: number;
  run_id: string;
  occurred_at: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  event_type: string;
  safe_message: string;
};

export type CrawlerSchedule = {
  schedule_id: string;
  source_id: string;
  enabled: boolean;
  timezone: string;
  /** 'HH:MM' (설정 API) 또는 'HH:MM:SS' (읽기 API) */
  local_time: string;
  mode: 'fixture' | 'live';
  next_run_at: string;
  last_run_at: string | null;
};

export type CrawlerSettings = {
  schedules: CrawlerSchedule[];
  night_window: { timezone: string; start: string; end: string; slot_minutes: number; max_slots: number; editable: false } | null;
  live_collection: 'HOLD';
  /** 서버 쓰기 API(T155 플래그)가 켜져 있는지. 꺼져 있으면 읽기 전용으로 표시합니다. */
  writeApi: boolean;
};

export type KeywordAuditEntry = {
  audit_id: number;
  keyword_id: number;
  actor: string;
  action: 'CREATE' | 'EDIT' | 'SET_ENABLED' | 'SOFT_DELETE';
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown>;
  occurred_at: string;
};

export type CommandResult = {
  command_id: string;
  command_type: 'RUN' | 'STOP' | 'RETRY' | 'SCHEDULE_UPDATE';
  target: string;
  outcome: 'ACCEPTED' | 'REFUSED';
  reason: string;
  result: Record<string, unknown>;
  replayed: boolean;
};

export type CommandRecord = Omit<CommandResult, 'replayed'> & { actor: string; created_at: string };

export type JobQuery = { status?: JobStatus; keyword_id?: number };

export interface CrawlerAdminService {
  listKeywordStats(signal?: AbortSignal): Promise<KeywordStat[]>;
  listJobs(query: JobQuery, signal?: AbortSignal): Promise<CrawlerJob[]>;
  listRuns(signal?: AbortSignal): Promise<CrawlerRun[]>;
  listRunEvents(runId: string, signal?: AbortSignal): Promise<RunEvent[]>;
  getSettings(signal?: AbortSignal): Promise<CrawlerSettings>;
  listCommands(signal?: AbortSignal): Promise<CommandRecord[]>;
  keywordAudit(keywordId: number, signal?: AbortSignal): Promise<KeywordAuditEntry[]>;
  createKeyword(input: { keyword: string; priority: number }): Promise<CrawlerKeyword>;
  updateKeyword(keywordId: number, input: { keyword: string; priority: number }): Promise<CrawlerKeyword>;
  setKeywordEnabled(keywordId: number, enabled: boolean): Promise<CrawlerKeyword>;
  deleteKeyword(keywordId: number): Promise<void>;
  runKeyword(keywordId: number, idempotencyKey: string): Promise<CommandResult>;
  stopJob(jobId: string, idempotencyKey: string): Promise<CommandResult>;
  retryJob(jobId: string, idempotencyKey: string): Promise<CommandResult>;
  updateScheduleTime(scheduleId: string, localTime: string, idempotencyKey: string): Promise<CommandResult>;
}

/** 서버 계약과 같은 검사 (서버도 다시 검사합니다). */
export const KEYWORD_MAX = 100;
export const LOCAL_TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

export function normalizeKeywordInput(value: string): string {
  return value.normalize('NFKC').split(/\s+/).filter(Boolean).join(' ');
}

/** 멱등 키: 버튼 한 번 누를 때마다 새로 만듭니다. 같은 요청을 다시 보낼 때만 재사용합니다. */
export function newIdempotencyKey(): string {
  return `ui:${globalThis.crypto.randomUUID()}`;
}

const REASON_TEXT: Record<string, string> = {
  KEYWORD_EXISTS: '같은 검색어가 이미 있습니다(삭제한 검색어 포함).',
  IDEMPOTENCY_KEY_REUSED: '같은 요청 번호로 다른 요청이 이미 처리되었습니다. 다시 시도해 주세요.',
  'LIVE_NOT_APPROVED:NOT_APPROVED': '실제 사이트 수집은 승인 전이라 실행할 수 없습니다(LIVE HOLD).',
  SCHEDULE_ACTIVATION_REQUIRES_APPROVAL: '스케줄 활성화는 별도 승인이 필요해 이 화면에서 할 수 없습니다.',
  ACTIVE_SCHEDULE_CHANGE_REQUIRES_APPROVAL: '활성 상태인 스케줄은 이 화면에서 바꿀 수 없습니다.',
  SCHEDULE_NOT_FOUND: '스케줄을 찾을 수 없습니다.',
  ACTIVE_JOB_EXISTS: '이 검색어에 대기·진행 중인 작업이 이미 있습니다.',
  KEYWORD_DISABLED: '비활성 검색어는 실행할 수 없습니다.',
  KEYWORD_NOT_FOUND: '검색어를 찾을 수 없습니다.',
  JOB_NOT_FOUND: '작업을 찾을 수 없습니다.',
  JOB_ALREADY_FINISHED: '이미 끝난 작업입니다.',
  RUNNING_JOB_STOP_UNSUPPORTED: '진행 중인 작업은 Worker 가 처리 중이라 화면에서 중단할 수 없습니다.',
  JOB_NOT_RETRYABLE: '실패·취소된 작업만 재시도할 수 있습니다.',
};

export type CrawlerAdminError = { message: string; forbidden: boolean; retry: boolean; reason?: string };

export function crawlerAdminErrorMessage(error: unknown): CrawlerAdminError {
  if (!(error instanceof ApiError)) return { message: '알 수 없는 오류가 발생했습니다.', forbidden: false, retry: true };
  const reason = error.headers?.get(COMMAND_REASON_HEADER) ?? undefined;
  switch (error.status) {
    case 0: return { message: '네트워크에 연결할 수 없습니다.', forbidden: false, retry: true };
    case 401: return { message: '로그인이 만료되었습니다. 다시 로그인해 주세요.', forbidden: true, retry: false };
    case 403: return { message: '관리자 권한이 없습니다. 권한이 회수되었을 수 있습니다.', forbidden: true, retry: false };
    case 404: return { message: '대상이 없거나 서버의 쓰기 API(CRAWLER_ADMIN_WRITE_API)가 꺼져 있습니다.', forbidden: false, retry: false };
    case 409: return {
      message: (reason && REASON_TEXT[reason]) ?? '현재 상태에서는 처리할 수 없습니다.',
      forbidden: false, retry: false, reason,
    };
    case 422: return { message: '입력값을 확인해 주세요.', forbidden: false, retry: false };
    case 503: return { message: '크롤러 데이터베이스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.', forbidden: false, retry: true };
    default: return { message: error.userMessage ?? '요청을 처리하지 못했습니다.', forbidden: false, retry: true };
  }
}

export function reasonText(reason: string): string {
  return REASON_TEXT[reason] ?? reason;
}
