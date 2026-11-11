/**
 * T94 계정 복구 Mock Adapter — 합성 데이터, 실제 메일 없음. T93 서버 규칙을 흉내 냅니다:
 * 가입 여부와 관계없이 같은 성공, 30분 유효·한 번만 쓰는 토큰, 사용 시 같은 계정의 남은 토큰 무효, 같은 400, 요청 한도(429).
 * 발급된 링크는 화면 개발·시험을 위해 `lastIssuedToken`(메모리)으로만 꺼낼 수 있습니다.
 */
import type { AccountRecoveryService } from '../api/accountRecovery';
import { ApiError } from '../api/errors';
import { REQUEST_PATH, RESET_PATH } from '../api/accountRecovery';

type Token = { email: string; expiresAt: number; used: boolean };

export type MockAccountRecoveryService = AccountRecoveryService & {
  lastIssuedToken: () => string | null;
  /** 시험용: 토큰을 만료시킴 */
  expire: (token: string) => void;
  calls: Array<{ path: string }>;
};

export function createMockAccountRecoveryService(options: {
  accounts?: string[]; unavailable?: boolean; now?: () => number; limitPerEmail?: number;
} = {}): MockAccountRecoveryService {
  const accounts = new Set((options.accounts ?? ['user@example.com']).map((e) => e.toLowerCase()));
  const now = options.now ?? (() => Date.now());
  const tokens = new Map<string, Token>();
  const requestsPerEmail = new Map<string, number>();
  const calls: MockAccountRecoveryService['calls'] = [];
  let last: string | null = null;
  let sequence = 0;

  return {
    calls,
    lastIssuedToken: () => last,
    expire: (token) => { const t = tokens.get(token); if (t) t.expiresAt = 0; },
    async requestReset({ email }) {
      calls.push({ path: REQUEST_PATH });
      if (options.unavailable) throw new ApiError(503, REQUEST_PATH, undefined, 'DEPENDENCY_UNAVAILABLE');
      const key = email.trim().toLowerCase();
      const count = (requestsPerEmail.get(key) ?? 0) + 1;
      requestsPerEmail.set(key, count);
      if (count > (options.limitPerEmail ?? 3)) throw new ApiError(429, REQUEST_PATH, undefined, 'RATE_LIMITED');
      if (!accounts.has(key)) return;                       // 같은 성공 — 없는 계정에는 아무것도 하지 않음
      sequence += 1;
      const token = `mock-reset-token-${sequence}-${'x'.repeat(24)}`;
      tokens.set(token, { email: key, expiresAt: now() + 30 * 60_000, used: false });
      last = token;
    },
    async resetPassword({ token, new_password: password }) {
      calls.push({ path: RESET_PATH });
      if (password.length < 10) throw new ApiError(422, RESET_PATH, undefined, 'VALIDATION_FAILED');
      const found = tokens.get(token);
      if (!found || found.used || found.expiresAt <= now()) throw new ApiError(400, RESET_PATH, undefined, 'INVALID_RESET_TOKEN');
      for (const t of tokens.values()) if (t.email === found.email) t.used = true;
    },
  };
}
