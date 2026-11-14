/**
 * T81 운영 콘텐츠 검수 실제 API Adapter (backend/app/routers/admin_moderation.py, 서버 ADMIN_MODERATION_API·migration 0010).
 * createApi 에 api.moderation 으로 등록되고, Mock 모드가 아닐 때 ModerationServiceProvider 가 고릅니다.
 * 확정 OpenAPI(T06) 병합 후 경로·DTO 를 생성 타입으로 다시 확인합니다.
 */
import type { HttpClient } from './http';
import type { ModerationCaseDetail, ModerationService } from './moderation';

const BASE = '/v1/admin/moderation-cases';

export function createHttpModerationService(http: HttpClient): ModerationService {
  const item = (caseId: string) => `${BASE}/${encodeURIComponent(caseId)}`;
  return {
    list: (query, signal) => http.request(BASE, { query: { ...query }, signal }),
    get: (caseId, signal) => http.request<ModerationCaseDetail>(item(caseId), { signal }),
    assign: (caseId, body) =>
      http.request<ModerationCaseDetail>(`${item(caseId)}/assignment`, { method: 'POST', body }),
    release: (caseId, body) =>
      http.request<ModerationCaseDetail>(`${item(caseId)}/assignment/release`, { method: 'POST', body }),
    decide: (caseId, body) =>
      http.request<ModerationCaseDetail>(`${item(caseId)}/decision`, { method: 'POST', body }),
  };
}
