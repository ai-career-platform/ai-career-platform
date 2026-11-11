// VITE_* 값은 빌드 시 브라우저 번들에 포함됩니다. 비밀정보(API Key, 비밀번호)를 넣지 않습니다.
export const env = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api',
  mockEnabled: import.meta.env.VITE_API_MOCK === 'true',
  /** T72 행동 이벤트 실제 전송 스위치. 운영 승인 전까지 기본 꺼짐 */
  behaviorTrackingEnabled: import.meta.env.VITE_BEHAVIOR_TRACKING === 'true',
  /**
   * T82 관리자 검수 화면. T81 API·T80 정책 승인 전이라 **Mock 모드에서만** 켤 수 있습니다.
   * 두 값이 모두 'true'여야 메뉴·경로가 생깁니다. 운영·일반 빌드(Mock 아님)에서는 항상 꺼짐.
   */
  adminModerationUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_ADMIN_MODERATION_UI === 'true',
  /**
   * T85 운영 감사·AI 사용량 화면. T60(사용량 기록)·T84 정책(D1~D5) 전이라 **Mock 모드에서만** 켤 수 있습니다.
   * 두 값이 모두 'true'여야 메뉴·경로가 생깁니다. 운영·일반 빌드에서는 항상 꺼짐. 켜져도 admin 역할만 들어갑니다.
   */
  adminAuditUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_ADMIN_AUDIT_UI === 'true',
  /**
   * T97 알림함·수신 설정 화면. 알림함 API 계약·서버(T96 발송 모듈은 API 없음) 전이라 **Mock 모드에서만** 켤 수 있습니다.
   * 두 값이 모두 'true'여야 메뉴·경로가 생깁니다. 운영·일반 빌드에서는 항상 꺼짐. 켜져도 로그인 사용자만 들어갑니다.
   */
  notificationsUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_NOTIFICATIONS_UI === 'true',
} as const;
