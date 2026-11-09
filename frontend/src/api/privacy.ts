/** 개인정보 설정 화면(T32)의 표시 이름. 호출은 createApi(http).me.consents / .me.deletion */
import type { ConsentPolicy } from './me';
import type { BodyOf } from './schema';

export type { ConsentPolicy, Consent as PrivacyConsent, DeletionRequest } from './me';

/** 사용자가 바꿀 수 있는 선택 약관 코드 (ConsentInput.policy_code). 필수 약관은 변경 API 대상이 아님 */
export type OptionalPolicyCode = BodyOf<'recordMyConsent'>['policy_code'];
export type OptionalPolicy = ConsentPolicy & { policy_code: OptionalPolicyCode };
const optionalCodes: readonly string[] = ['llm_processing', 'behavior_tracking'] satisfies OptionalPolicyCode[];
export const isOptionalPolicy = (policy: ConsentPolicy): policy is OptionalPolicy =>
  !policy.is_required && optionalCodes.includes(policy.policy_code);

export const policyNames: Record<string, string> = {
  terms: '이용약관', privacy: '개인정보 처리',
  llm_processing: 'AI 처리', behavior_tracking: '행동 기록',
};
