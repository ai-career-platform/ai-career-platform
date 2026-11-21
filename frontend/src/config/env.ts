// VITE_* 값은 빌드 시 브라우저 번들에 포함됩니다. 비밀정보(API Key, 비밀번호)를 넣지 않습니다.
import { defaultApiBaseUrl } from './basePath';

export const env = {
  /** 기본은 앱 경로 아래 api: '/api'(로컬), '/career/api'(Staging, VITE_BASE_PATH=/career/) */
  apiBaseUrl: defaultApiBaseUrl(import.meta.env.VITE_API_BASE_URL as string | undefined, import.meta.env.BASE_URL),
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
   * T97 알림함·수신 설정 화면. 기본 꺼짐. Mock 모드면 Mock Adapter, 아니면 실제 API(T97)를 씁니다. 로그인 사용자만 들어갑니다.
   * 실제 API 로 켜려면 서버 NOTIFICATIONS_API=true 와 migration 0005 적용이 먼저 필요합니다(운영은 별도 승인).
   */
  notificationsUi: import.meta.env.VITE_NOTIFICATIONS_UI === 'true',
  /** T100 고급 채용 검색 UI: Mock일 때만 활성화. */
  jobSearchAdvancedUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_JOB_SEARCH_ADVANCED_UI === 'true',
  /**
   * T103 지원 현황 보드·공고 상세의 "지원 기록에 추가". 기본 꺼짐. Mock 모드면 Mock Adapter, 아니면 실제 API(T102)를 씁니다.
   * 실제 API 로 켜려면 서버 JOB_APPLICATIONS_API=true 와 migration 0004 적용이 먼저 필요합니다(운영은 별도 승인).
   */
  applicationsUi: import.meta.env.VITE_APPLICATIONS_UI === 'true',
  /**
   * T156 크롤러 관리자 콘솔. 기본 비활성, 서버 T155 쓰기 플래그 별도 적용.
   * 실제 API 또는 Mock에서 관리자가 켤 수 있으나 활성화는 별도 승인 사항입니다.
   */
  crawlerAdminUi: import.meta.env.VITE_CRAWLER_ADMIN_UI === 'true',
  /**
   * T124 기업 콘솔(조직·멤버·초대, /company·/company-invitations/accept). 기본 꺼짐. Mock 모드면 Mock Adapter,
   * 아니면 실제 API(T123). 실제 API 로 켜려면 서버 COMPANY_ACCOUNTS_API=true 와 migration 0008 이 먼저 필요합니다
   * (운영은 별도 승인. 메일 공급자 연결 전에는 초대 생성·재전송이 503).
   */
  companyConsoleUi: import.meta.env.VITE_COMPANY_CONSOLE_UI === 'true',
  /** T127 기업 공고 관리 콘솔. 기업 콘솔 플래그와 함께 켜야 하며 Mock 모드 전용(T125·T126 미승인). */
  companyPostingsUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_COMPANY_CONSOLE_UI === 'true'
    && import.meta.env.VITE_COMPANY_POSTINGS_UI === 'true',
  /**
   * T140 기술 자동완성(동의어·표준 코드). T139 서버 API 도 기본 꺼짐(SKILL_AUTOCOMPLETE_API)이라 둘 다 켜야 합니다.
   * Mock 모드에서는 가상 동의어로 동작합니다. 꺼져 있으면 기존 T17 이름 검색을 그대로 씁니다.
   */
  skillAutocomplete: import.meta.env.VITE_SKILL_AUTOCOMPLETE === 'true',
  /**
   * T130 공개 포트폴리오(설정 /me/public-profile, 공개 보기 /p/:token). 기본 꺼짐. Mock 모드면 Mock Adapter, 아니면 실제 API(T129).
   * 실제 API 로 켜려면 서버 PUBLIC_PORTFOLIO_API=true, migration 0007, 'public_profile' 약관 행이 먼저 필요합니다(운영은 별도 승인).
   */
  publicPortfolioUi: import.meta.env.VITE_PUBLIC_PORTFOLIO_UI === 'true',
  /**
   * T143 내 데이터 내려받기. 기본 꺼짐. Mock 모드면 Mock Adapter, 아니면 실제 API(T142)를 씁니다.
   * 실제 API 로 켜려면 서버 PERSONAL_DATA_REQUESTS_API=true 와 migration 0006 적용이 먼저 필요합니다(운영은 별도 승인).
   */
  personalDataUi: import.meta.env.VITE_PERSONAL_DATA_UI === 'true',
} as const;
