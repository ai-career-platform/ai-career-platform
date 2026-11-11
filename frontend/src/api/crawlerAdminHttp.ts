/**
 * T156 실제 API Adapter (T155 읽기 #124 + 쓰기 #233). HttpClient baseUrl '/api' + '/v1/admin/crawler/...'.
 * - 명령은 Idempotency-Key 헤더를 붙입니다(HttpRequest.headers). 토큰·CSRF 는 세션 클라이언트가 붙입니다.
 * - /settings 가 404 면 서버 쓰기 API 가 꺼진 것으로 보고 읽기 API(/schedules)로 대신 보여 줍니다.
 */
import {
  CRAWLER_ADMIN_BASE,
  type CommandRecord, type CommandResult, type CrawlerAdminService, type CrawlerJob, type CrawlerKeyword,
  type CrawlerRun, type CrawlerSchedule, type CrawlerSettings, type KeywordAuditEntry, type KeywordStat, type RunEvent,
} from './crawlerAdmin';
import { ApiError } from './errors';
import type { HttpClient } from './http';

const LIST_LIMIT = 100;

export function createHttpCrawlerAdminService(http: HttpClient): CrawlerAdminService {
  const command = (path: string, body: unknown, key: string, method: 'POST' | 'PATCH' = 'POST') =>
    http.request<CommandResult>(`${CRAWLER_ADMIN_BASE}${path}`, { method, body, headers: { 'Idempotency-Key': key } });

  return {
    listKeywordStats: (signal) =>
      http.request<KeywordStat[]>(`${CRAWLER_ADMIN_BASE}/stats/keywords`, { query: { limit: LIST_LIMIT }, signal }),
    listJobs: ({ status, keyword_id }, signal) =>
      http.request<CrawlerJob[]>(`${CRAWLER_ADMIN_BASE}/jobs`, { query: { limit: LIST_LIMIT, status, keyword_id }, signal }),
    listRuns: (signal) => http.request<CrawlerRun[]>(`${CRAWLER_ADMIN_BASE}/runs`, { query: { limit: 50 }, signal }),
    listRunEvents: (runId, signal) =>
      http.request<RunEvent[]>(`${CRAWLER_ADMIN_BASE}/runs/${encodeURIComponent(runId)}/events`, { query: { limit: 50 }, signal }),
    async getSettings(signal) {
      try {
        const settings = await http.request<Omit<CrawlerSettings, 'writeApi'>>(`${CRAWLER_ADMIN_BASE}/settings`, { signal });
        return { ...settings, writeApi: true };
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        const schedules = await http.request<CrawlerSchedule[]>(`${CRAWLER_ADMIN_BASE}/schedules`, { signal });
        return { schedules, night_window: null, live_collection: 'HOLD', writeApi: false };
      }
    },
    listCommands: (signal) => http.request<CommandRecord[]>(`${CRAWLER_ADMIN_BASE}/commands`, { query: { limit: 50 }, signal }),
    keywordAudit: (keywordId, signal) =>
      http.request<KeywordAuditEntry[]>(`${CRAWLER_ADMIN_BASE}/keywords/${keywordId}/audit`, { query: { limit: 20 }, signal }),
    createKeyword: (input) =>
      http.request<CrawlerKeyword>(`${CRAWLER_ADMIN_BASE}/keywords`, { method: 'POST', body: input }),
    updateKeyword: (keywordId, input) =>
      http.request<CrawlerKeyword>(`${CRAWLER_ADMIN_BASE}/keywords/${keywordId}`, { method: 'PATCH', body: input }),
    setKeywordEnabled: (keywordId, enabled) =>
      http.request<CrawlerKeyword>(`${CRAWLER_ADMIN_BASE}/keywords/${keywordId}/enabled`, { method: 'PUT', body: { enabled } }),
    deleteKeyword: async (keywordId) => {
      await http.request<void>(`${CRAWLER_ADMIN_BASE}/keywords/${keywordId}`, { method: 'DELETE' });
    },
    runKeyword: (keywordId, key) => command('/commands/run', { keyword_id: keywordId, mode: 'fixture' }, key),
    stopJob: (jobId, key) => command('/commands/stop', { job_id: jobId }, key),
    retryJob: (jobId, key) => command('/commands/retry', { job_id: jobId }, key),
    updateScheduleTime: (scheduleId, localTime, key) =>
      command(`/schedules/${encodeURIComponent(scheduleId)}`, { local_time: localTime }, key, 'PATCH'),
  };
}
