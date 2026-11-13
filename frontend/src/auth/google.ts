/**
 * #328 Google 로그인 (Backend PR #330, 설계 docs/security/GOOGLE_SSO_AUTO_SIGNUP_DESIGN.md).
 *
 * - OAuth 는 Backend 가 전부 처리합니다. 화면은 시작 주소로 **전체 페이지 이동**만 하고, code·Google 토큰·Client Secret 을
 *   다루지 않습니다. 세션은 기존 HttpOnly refresh 쿠키 + POST /auth/refresh 로만 복원합니다.
 * - 아래 호출은 세션 클라이언트가 아니라 `publicHttp`(토큰 없음, 401 이 세션을 끊지 않음)로 보냅니다.
 *   예: 로컬 로그인 상태에서 게이트 확인이 401 이어도 로그인 세션은 유지되어야 합니다.
 */
import { ApiError } from '../api/errors';
import type { HttpClient } from '../api/http';
import type { BodyOf, ResponseOf } from '../api/schema';
import { routerBasename } from '../config/basePath';

export type GooglePending = ResponseOf<'getGooglePendingSignup'>;
export type GoogleSignupBody = BodyOf<'completeGoogleSignup'>;
export type TokenResponse = ResponseOf<'completeGoogleSignup'>;

/** 로그인 화면에 보여 줄 Backend 오류 코드 (google_error 쿼리). 그 밖의 값은 무시합니다. */
export const GOOGLE_LOGIN_ERRORS = {
  failed: 'Google 로그인을 완료하지 못했습니다. 다시 시도해 주세요.',
  cancelled: 'Google 로그인이 취소되었습니다.',
  email_conflict: '이 이메일로 가입된 계정이 있습니다. 기존 비밀번호로 로그인해 주세요. (Google 계정은 자동으로 연결하지 않습니다)',
} as const;
export type GoogleLoginError = keyof typeof GOOGLE_LOGIN_ERRORS;

export function googleLoginError(value: string | null): string | null {
  return value !== null && Object.prototype.hasOwnProperty.call(GOOGLE_LOGIN_ERRORS, value)
    ? GOOGLE_LOGIN_ERRORS[value as GoogleLoginError] : null;
}

/** Google 인증을 마친 뒤 Backend 가 보내는 SPA 경로(라우터 기준). AuthProvider 가 첫 refresh 전에 확인합니다. */
export const GOOGLE_DONE_PATH = '/auth/google/done';
export const GOOGLE_SIGNUP_PATH = '/auth/google/signup';

const basePrefix = (): string => routerBasename(import.meta.env.BASE_URL) ?? '';

/** 라우터 경로 → 같은 사이트 내부 경로인지. 외부·상위 경로·API 경로는 거부합니다. */
export function isSafeAppPath(path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//') || path.length > 512) return false;
  if ([...path].some((c) => c === '\\' || c === '@' || c.charCodeAt(0) < 0x20)) return false;
  let decoded: string;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    return false;
  }
  if (decoded.startsWith('//') || decoded.includes('\\')) return false;
  const pathname = decoded.split(/[?#]/, 1)[0] ?? '';
  if (pathname.split('/').some((segment) => segment === '.' || segment === '..')) return false;
  return !(pathname === '/api' || pathname.startsWith('/api/'));
}

/**
 * Backend 가 넘긴 `next`(외부 전체 경로, 예: '/career/me/skills') → 라우터 경로('/me/skills').
 * 앱 접두사로 시작하지 않거나 안전하지 않으면 홈('/').
 */
export function nextAppPath(next: string | null, prefix: string = basePrefix()): string {
  if (!next) return '/';
  if (prefix) {
    if (next !== prefix && !next.startsWith(`${prefix}/`)) return '/';
    next = next.slice(prefix.length) || '/';
  }
  return isSafeAppPath(next) ? next : '/';
}

/** Google 로그인 시작 주소(전체 페이지 이동용). returnPath 는 라우터 경로, Backend 에는 외부 전체 경로로 넘깁니다. */
export function googleStartHref(apiBaseUrl: string, returnPath = '/', options: { selectAccount?: boolean } = {}): string {
  const params = new URLSearchParams();
  const safe = isSafeAppPath(returnPath) ? returnPath : '/';
  params.set('return_to', `${basePrefix()}${safe}`);
  if (options.selectAccount) params.set('prompt', 'select_account');
  return `${apiBaseUrl}/v1/auth/google/start?${params.toString()}`;
}

/** 완전 로그아웃 뒤 이동(테스트에서 바꿀 수 있게 분리). */
export const navigation = { assign: (href: string) => window.location.assign(href) };

/** 완전 로그아웃 뒤 이동할 정적 페이지(게이트 밖). SPA 로 돌아오면 게이트가 다시 Google 로 보내므로 루프가 됩니다. */
export const googleSignedOutHref = (apiBaseUrl: string): string => `${apiBaseUrl}/v1/auth/google/signed-out`;

export const googleApi = (http: HttpClient) => ({
  /**
   * 이 서버에서 Google 로그인을 쓸 수 있는지. GET /auth/gate 는 기능이 꺼져 있으면 404(경로 없음),
   * 켜져 있으면 204(게이트 통과) 또는 401(아직 Google 인증 전)입니다. 그 밖의 오류는 '쓸 수 없음'으로 봅니다.
   */
  async available(signal?: AbortSignal): Promise<boolean> {
    try {
      await http.request<undefined>('/v1/auth/gate', { token: null, signal });
      return true;
    } catch (error) {
      if (error instanceof ApiError) return error.status === 401;
      throw error; // AbortError 는 호출자에게
    }
  },
  pending: (signal?: AbortSignal) =>
    http.request<GooglePending>('/v1/auth/google/pending', { token: null, signal }),
  signup: (body: GoogleSignupBody) =>
    http.request<TokenResponse>('/v1/auth/google/signup', { method: 'POST', body, token: null }),
  /** 완전 로그아웃: 앱 세션 + Google 게이트 쿠키 종료(Google 계정 자체는 로그아웃하지 않음). */
  signout: () => http.request<undefined>('/v1/auth/google/signout', { method: 'POST', token: null }),
});
