/**
 * T84 실제 API Adapter — **현재 확정 계약만** 지원합니다.
 *   GET /api/v1/admin/audit-events  (HttpClient baseUrl '/api' + 경로 '/v1/...', 중복 없음)
 *   GET /api/v1/admin/ai-usage      (응답 헤더 X-AI-Cost-Status 를 읽음)
 * Mock 모드가 아니면 AdminAuditServiceProvider 가 이 Adapter 를 씁니다(useApi().adminAudit).
 * 화면 자체는 env.adminAuditUi(기본 꺼짐)가 켜졌을 때만 라우트에 들어갑니다.
 */
import {
  AUDIT_PATH, COST_STATUS_HEADER, USAGE_PATH, parseCostStatus,
  type AdminAuditService, type AiUsageBucket, type AuditEventPage, type CostStatus,
} from './adminAudit';
import type { HttpClient } from './http';

export function createHttpAdminAuditService(http: HttpClient): AdminAuditService {
  return {
    source: 'api',
    listEvents: ({ from, to, action_code, limit, cursor }, signal) =>
      http.request<AuditEventPage>(AUDIT_PATH, { query: { from, to, action_code, limit, cursor }, signal }),
    async getUsage({ from, to, group_by }, signal) {
      let costStatus: CostStatus = 'unknown';
      const buckets = await http.request<AiUsageBucket[]>(USAGE_PATH, {
        query: { from, to, group_by }, signal,
        onResponseHeaders: (headers) => { costStatus = parseCostStatus(headers.get(COST_STATUS_HEADER)); },
      });
      return { buckets, costStatus, source: 'api' };
    },
  };
}
