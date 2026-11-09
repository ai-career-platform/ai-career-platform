/**
 * T22 개발용 가상 데이터 — 내 프로필(GET·PATCH /v1/me). DB·영구 저장 없음.
 * 검증 규칙은 Backend T16(MePatch)과 같게 맞춥니다(Mock 성공은 실제 서비스 PASS가 아님).
 * 실제 서버의 422 응답에는 필드 정보가 없어(code·status·message만) Mock도 같은 모양으로 돌려줍니다.
 */
import { ApiError } from '../api/errors';
import type { MockRequest } from './handlers';

interface MockProfile {
  display_name: string;
  headline: string | null;
  bio: string | null;
  location_text: string | null;
}

const LIMITS: Record<keyof MockProfile, number> = { display_name: 100, headline: 200, bio: 5000, location_text: 120 };

const profiles = new Map<string, MockProfile>();
let failNext: { status: number; method: string } | null = null;

export function resetProfileMocks() {
  profiles.clear();
  failNext = null;
}
/** 테스트·개발용: 다음 /v1/me 요청(GET 또는 PATCH) 한 번을 지정한 HTTP 상태로 실패시킵니다. */
export function failNextProfileRequest(method: 'GET' | 'PATCH', status: number) {
  failNext = { status, method };
}

const fail = (status: number, code: string): never => {
  throw new ApiError(status, '', undefined, code);
};

/** 처음 접속한 사용자의 기본 프로필 */
const initialProfile = (email: string, displayName: string): MockProfile =>
  email === 'user@example.com'
    ? { display_name: displayName, headline: '백엔드 개발자 지망생', bio: null, location_text: '서울' }
    : { display_name: displayName, headline: null, bio: null, location_text: null };

function validate(patch: Record<string, unknown>) {
  const keys = Object.keys(patch);
  if (keys.length === 0) fail(422, 'VALIDATION_FAILED');
  for (const key of keys) {
    const value = patch[key];
    if (!(key in LIMITS)) fail(422, 'VALIDATION_FAILED');
    if (key === 'display_name' && (typeof value !== 'string' || value.trim() === '')) fail(422, 'VALIDATION_FAILED');
    if (value !== null && (typeof value !== 'string' || value.length > LIMITS[key as keyof MockProfile])) fail(422, 'VALIDATION_FAILED');
  }
}

export function resolveProfileMock(request: MockRequest, email: string, displayName: string) {
  if (failNext?.method === request.method) {
    const { status } = failNext;
    failNext = null;
    return fail(status, status === 503 ? 'DEPENDENCY_UNAVAILABLE' : 'INTERNAL_ERROR');
  }
  let current = profiles.get(email);
  if (!current) profiles.set(email, (current = initialProfile(email, displayName)));
  if (request.method === 'PATCH') {
    const patch = (request.body ?? {}) as Record<string, unknown>;
    validate(patch);
    current = { ...current, ...(patch as Partial<MockProfile>) };
    profiles.set(email, current);
  }
  const { display_name, ...profile } = current;
  return { user_id: email, email, display_name, status: 'active', profile };
}
