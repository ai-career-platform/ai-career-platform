/**
 * T81 이후 연결할 실제 API Adapter (T80 구현 계약 §4의 제안 경로).
 * **지금은 어떤 화면도 이 Adapter를 쓰지 않습니다.** T81 API·OpenAPI가 main에 없으므로 연결하면 404가 납니다.
 * T81 병합 후: 경로·DTO를 OpenAPI 생성 타입으로 확인하고 ModerationServiceProvider 에서 이 Adapter를 고릅니다.
 */
import type { HttpClient } from './http';
import type { ModerationCaseDetail, ModerationService } from './moderation';

const BASE = '/v1/admin/moderation-cases';

export function createHttpModerationService(http: HttpClient): ModerationService {
  return {
    list: (query, signal) => http.request(BASE, { query: { ...query }, signal }),
    get: (caseId, signal) => http.request<ModerationCaseDetail>(`${BASE}/${encodeURIComponent(caseId)}`, { signal }),
    assign: (caseId, body) =>
      http.request<ModerationCaseDetail>(`${BASE}/${encodeURIComponent(caseId)}/assignment`, { method: 'POST', body }),
    decide: (caseId, body) =>
      http.request<ModerationCaseDetail>(`${BASE}/${encodeURIComponent(caseId)}/decision`, { method: 'POST', body }),
  };
}
