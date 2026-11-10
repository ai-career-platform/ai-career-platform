/**
 * UI-028 운영 감사·AI 사용량 화면의 데이터 계약 (T85).
 * 타입은 docs/api/openapi.yaml(T84 **확정 계약**)에서 생성한 schema.gen.ts 를 그대로 씁니다.
 * T84 의 미승인 제안(D1~D5: 마스킹 응답, AiUsageReport, 90일 제한 등)은 현재 응답으로 가정하지 않습니다.
 */
import { ApiError } from './errors';
import type { QueryOf, Schemas } from './schema';

export type AuditEvent = Schemas['AuditEvent'];
export type AuditEventPage = Schemas['AuditEventPage'];
export type AiUsageBucket = Schemas['AiUsageBucket'];
export type UsageGroupBy = NonNullable<QueryOf<'getAiUsage'>['group_by']>;

/**
 * 감사 목록 조회 조건. 확정 계약의 `actor_user_id` 필터는 **일부러 넣지 않았습니다** —
 * GET 쿼리 문자열이라 서버·프록시 접근 로그에 원문 사용자 ID 가 남을 수 있기 때문입니다(T84 보고서 §8, 미해결).
 */
export type AuditQuery = {
  /** 포함. UTC 오프셋이 있는 ISO 8601 (예: 2026-11-01T00:00:00+09:00) */
  from: string;
  /** 제외 */
  to: string;
  action_code?: string;
  limit?: number;
  cursor?: string;
};

export type UsageQuery = { from: string; to: string; group_by: UsageGroupBy };

/**
 * 비용 검증 상태. 화면은 어떤 경우에도 "검증 완료"를 표시하지 않습니다.
 * - unverified: 서버가 `X-AI-Cost-Status: unverified` 를 보냄 (T84 현재 동작)
 * - unknown: 헤더가 없거나 모르는 값 → 역시 검증되지 않은 것으로 다룸
 */
export type CostStatus = 'unverified' | 'unknown';
export const COST_STATUS_HEADER = 'X-AI-Cost-Status';

export function parseCostStatus(value: string | null | undefined): CostStatus {
  return value === 'unverified' ? 'unverified' : 'unknown';
}

export type AiUsageResult = {
  buckets: AiUsageBucket[];
  costStatus: CostStatus;
  /** 'mock' 이면 화면이 "가상 데이터"를 함께 표시합니다. */
  source: 'mock' | 'api';
};

export interface AdminAuditService {
  listEvents(query: AuditQuery, signal?: AbortSignal): Promise<AuditEventPage>;
  getUsage(query: UsageQuery, signal?: AbortSignal): Promise<AiUsageResult>;
}

export const AUDIT_PATH = '/v1/admin/audit-events';
export const USAGE_PATH = '/v1/admin/ai-usage';
export const AUDIT_PAGE_SIZE = 20;
export const ACTION_CODE_PATTERN = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$/;

export const GROUP_BY_LABELS: Record<UsageGroupBy, string> = {
  day: '일별 (KST)', feature_code: '기능별', provider_model: '모델별',
};
export const FEATURE_LABELS: Record<string, string> = {
  document_analysis: '문서 분석', rag_answer: 'RAG 답변', agent: 'Agent',
};

export type AdminErrorView = { message: string; resetCursor: boolean; retry: boolean; forbidden?: boolean };

/** 서버 오류 → 화면 문구. 서버 메시지 원문 대신 고정 문구를 써서 내부 정보가 화면에 나오지 않게 합니다. */
export function adminAuditErrorMessage(error: unknown): AdminErrorView {
  if (error instanceof ApiError) {
    if (error.code === 'INVALID_CURSOR' || error.status === 400) {
      return { message: '목록 위치 정보가 만료되었거나 조건과 맞지 않습니다. 처음부터 다시 조회해 주세요.', resetCursor: true, retry: false };
    }
    if (error.status === 401) return { message: '로그인이 만료되었습니다. 다시 로그인해 주세요.', resetCursor: false, retry: false };
    if (error.status === 403) {
      return { message: '이 화면을 볼 권한이 없습니다. 관리자 권한(감사 기록 조회)이 회수되었을 수 있습니다.', resetCursor: false, retry: false, forbidden: true };
    }
    if (error.status === 422) return { message: '조회 조건을 확인해 주세요. 기간과 작업 코드 형식이 올바르지 않습니다.', resetCursor: false, retry: false };
    if (error.status === 503 || error.status === 0) {
      return { message: '서비스를 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.', resetCursor: false, retry: true };
    }
  }
  return { message: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.', resetCursor: false, retry: true };
}
