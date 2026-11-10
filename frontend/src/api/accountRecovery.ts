/**
 * UI-N03 계정 복구 (T94). 타입은 확정 계약(T06 `requestPasswordReset`·`resetPassword`)의 생성 타입을 씁니다.
 * Backend 구현(T93 PR #195)은 미병합 — 화면은 Mock Adapter 로만 동작하고, HTTP Adapter 는 준비만 합니다.
 * 토큰·비밀번호는 로그·콘솔·분석 이벤트에 남기지 않습니다.
 */
import { ApiError } from './errors';
import type { HttpClient } from './http';
import type { Schemas } from './schema';

export type PasswordResetRequestBody = Schemas['PasswordResetRequest'];
export type PasswordResetBody = Schemas['PasswordReset'];

export interface AccountRecoveryService {
  /** 가입 여부와 관계없이 성공(202)이면 같은 안내를 보여 줍니다. */
  requestReset(body: PasswordResetRequestBody): Promise<void>;
  /** 성공(204)하면 이 계정의 모든 세션이 종료됩니다. */
  resetPassword(body: PasswordResetBody): Promise<void>;
}

export const REQUEST_PATH = '/v1/auth/password-reset-requests';
export const RESET_PATH = '/v1/auth/password-resets';
export const MIN_PASSWORD = 10;
export const MAX_PASSWORD = 128;

/** 인증 토큰 없이(token: null) 보냅니다 — 로그인하지 않은 사용자의 공개 경로입니다. */
export function createHttpAccountRecoveryService(http: HttpClient): AccountRecoveryService {
  return {
    requestReset: (body) => http.request<void>(REQUEST_PATH, { method: 'POST', body, token: null }),
    resetPassword: (body) => http.request<void>(RESET_PATH, { method: 'POST', body, token: null }),
  };
}

export type RecoveryErrorView = { kind: 'invalid-token' | 'rate-limited' | 'unavailable' | 'invalid-input' | 'unknown';
  message: string };

/** 서버 오류 → 고정 문구. 계정 존재 여부를 드러내는 문구는 쓰지 않습니다. */
export function recoveryErrorView(error: unknown): RecoveryErrorView {
  if (error instanceof ApiError) {
    if (error.code === 'INVALID_RESET_TOKEN' || error.status === 400) {
      return { kind: 'invalid-token', message: '재설정 링크가 만료되었거나 이미 사용되었습니다. 새 링크를 다시 요청해 주세요.' };
    }
    if (error.status === 429) {
      return { kind: 'rate-limited', message: '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.' };
    }
    if (error.status === 422) return { kind: 'invalid-input', message: '입력한 내용을 확인해 주세요.' };
    if (error.status === 503 || error.status === 0) {
      return { kind: 'unavailable', message: '지금은 비밀번호 재설정 메일을 보낼 수 없습니다. 잠시 후 다시 시도하거나 운영자에게 문의해 주세요.' };
    }
  }
  return { kind: 'unknown', message: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' };
}
