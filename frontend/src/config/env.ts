// VITE_* 값은 빌드 시 브라우저 번들에 포함됩니다. 비밀정보(API Key, 비밀번호)를 넣지 않습니다.
export const env = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api',
  mockEnabled: import.meta.env.VITE_API_MOCK === 'true',
  /** T72 행동 이벤트 실제 전송 스위치. 운영 승인 전까지 기본 꺼짐 */
  behaviorTrackingEnabled: import.meta.env.VITE_BEHAVIOR_TRACKING === 'true',
} as const;
