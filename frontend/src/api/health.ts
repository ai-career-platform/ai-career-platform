import { apiGet, type ApiClientOptions } from './client';

// 현재 Backend에 실제 구현된 API (poc/staging/backend, backend/app)
export interface HealthResponse {
  status: string;
  service: string;
}

export interface VersionResponse {
  application: string;
  environment: string;
  version: string;
}

export const getHealth = (options?: ApiClientOptions) => apiGet<HealthResponse>('/health', options);
export const getVersion = (options?: ApiClientOptions) => apiGet<VersionResponse>('/version', options);
export const getDbHealth = (options?: ApiClientOptions) => apiGet<HealthResponse>('/health/db', options);
