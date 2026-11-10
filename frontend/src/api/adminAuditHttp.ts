/**
 * T84 실제 API Adapter — **현재 확정 계약만** 지원합니다.
 *   GET /api/v1/admin/audit-events  (HttpClient baseUrl '/api' + 경로 '/v1/...', 중복 없음)
 *   GET /api/v1/admin/ai-usage      (응답 헤더 X-AI-Cost-Status 를 읽음)
 * 지금은 어떤 화면도 이 Adapter 를 고르지 않습니다(AdminAuditServiceProvider 는 Mock 만 사용).
 * 운영 연결은 T60(사용량 기록)·T84 정책(D1~D5)·접근 로그 문제 해결 후 별도 단계입니다.
 */
import {
  AUDIT_PATH, COST_STATUS_HEADER, USAGE_PATH, parseCostStatus,
  type AdminAuditService, type AiUsageBucket, type AuditEventPage, type CostStatus,
} from './adminAudit';
import type { HttpClient } from './http';

export function createHttpAdminAuditService(http: HttpClient): AdminAuditService {
  return {
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
