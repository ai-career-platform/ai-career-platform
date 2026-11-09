import type { HttpClient } from './http';

// 현재 Backend에 실제 구현된 상태 확인 API (poc/staging/backend, backend/app). /v1 밖의 경로입니다.
export interface HealthResponse {
  status: string;
  service: string;
}

export interface VersionResponse {
  application: string;
  environment: string;
  version: string;
}

export const systemApi = (http: HttpClient) => ({
  health: (signal?: AbortSignal) => http.request<HealthResponse>('/health', { signal }),
  version: (signal?: AbortSignal) => http.request<VersionResponse>('/version', { signal }),
  dbHealth: (signal?: AbortSignal) => http.request<HealthResponse>('/health/db', { signal }),
});
