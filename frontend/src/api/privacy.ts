export interface ConsentPolicy {
  policy_code: string;
  version: string;
  is_required: boolean;
  content_url: string;
  effective_at: string;
}
export interface PrivacyConsent {
  consent_id: string;
  is_required: boolean;
  policy_code: string;
  policy_version: string;
  granted: boolean;
  recorded_at: string;
}
export interface DeletionRequest {
  request_id: string;
  status: 'requested' | 'cancelled' | 'completed';
  requested_at: string;
  scheduled_purge_at: string | null;
  completed_at: string | null;
}
export const policyNames: Record<string, string> = {
  terms: '이용약관', privacy: '개인정보 처리',
  llm_processing: 'AI 처리', behavior_tracking: '행동 기록',
};
