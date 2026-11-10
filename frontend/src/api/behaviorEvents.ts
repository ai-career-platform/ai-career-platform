/**
 * T72 동의 기반 행동 이벤트 클라이언트 (docs/data/BEHAVIOR_EVENT_CONTRACT.md, POST /v1/me/behavior-events).
 *
 * - 기본 비활성: `enabled`(env.behaviorTrackingEnabled, 기본 false)가 아니면 아무 요청도 보내지 않습니다.
 * - 동의: 보낼 때마다 `hasConsent()`를 확인합니다. 서버도 다시 확인하므로 이 값만 믿지 않습니다.
 * - 철회: `revoke()` 또는 서버의 blocked_no_consent 응답 뒤에는 즉시 멈춥니다.
 * - 허용 이벤트: 승인된 tracking 5종만 보냅니다. personalization 3종(T71 미승인)은 보내지 않습니다.
 * - 재시도: 네트워크 오류·5xx 때 같은 event_id로 다시 보냅니다(서버 중복 저장 없음).
 * - 실패해도 화면 동작을 막지 않습니다: track()은 예외를 던지지 않고 결과 코드만 돌려줍니다.
 * - 화면에 자동 추적 코드를 넣지 않습니다. 호출하는 곳이 명시적으로 track()을 부릅니다.
 */
import { ApiError } from './errors';
import type { HttpClient } from './http';
import type { Consent } from './me';
import type { BodyOf, Schemas } from './schema';

export type BehaviorEventInput = BodyOf<'recordMyBehaviorEvent'>;
export type BehaviorEventResult = Schemas['BehaviorEventResult'];

export const behaviorEventsApi = (http: HttpClient) => ({
  record: (event: BehaviorEventInput) =>
    http.request<BehaviorEventResult>('/v1/me/behavior-events', { method: 'POST', body: event }),
});

/** T71 계약 tracking 이벤트와 허용 metadata 키 (서버 TRACKING_EVENTS와 같음) */
export const TRACKING_EVENTS = {
  'page.view': ['page_id', 'referrer_type'],
  'search.submit': ['search_type', 'filter_count', 'result_count'],
  'posting.view': ['job_posting_id', 'list_position'],
  'role.view': ['job_role_id'],
  'skill_gap.view': ['job_role_id', 'gap_count'],
} as const satisfies Partial<Record<BehaviorEventInput['event_code'], readonly string[]>>;

export type TrackingEventCode = keyof typeof TRACKING_EVENTS;
type MetadataValue = number | boolean | string;
export type TrackingMetadata<C extends TrackingEventCode> = Partial<Record<(typeof TRACKING_EVENTS)[C][number], MetadataValue>>;

const ID_OR_CODE = /^[A-Za-z0-9_.:-]{1,64}$/;

/** 허용 키·값 규칙(숫자, true/false, 공백 없는 ID/코드)을 지키는지. 검색어 원문·문장은 통과하지 못합니다. */
export function isAllowedMetadata(code: string, metadata: Record<string, unknown> | undefined): boolean {
  const allowed: readonly string[] | undefined = TRACKING_EVENTS[code as TrackingEventCode];
  if (!allowed) return false;
  return Object.entries(metadata ?? {}).every(([key, value]) => allowed.includes(key) && (
    typeof value === 'boolean'
    || (typeof value === 'number' && Number.isFinite(value))
    || (typeof value === 'string' && ID_OR_CODE.test(value))));
}

/** GET /me/consents 이력에서 behavior_tracking 최신 동의 여부 (없으면 false) */
export function behaviorTrackingGranted(consents: readonly Consent[]): boolean {
  const latest = consents
    .filter((c) => c.policy_code === 'behavior_tracking')
    .reduce<Consent | null>((a, b) => (!a || b.recorded_at > a.recorded_at ? b : a), null);
  return latest?.granted ?? false;
}

export type TrackOutcome =
  | BehaviorEventResult['status']
  | 'skipped_disabled' | 'skipped_no_consent' | 'skipped_not_allowed' | 'failed';

export interface BehaviorTrackerOptions {
  /** 실제 수집 스위치. 기본 꺼짐 (env.behaviorTrackingEnabled) */
  enabled: boolean;
  /** 현재 behavior_tracking 동의 상태 (behaviorTrackingGranted(consents) 등) */
  hasConsent: () => boolean;
  send: (event: BehaviorEventInput) => Promise<BehaviorEventResult>;
  newEventId?: () => string;
  now?: () => Date;
  /** 같은 event_id로 보낼 최대 횟수 (기본 2) */
  maxAttempts?: number;
}

const retriable = (error: unknown) => error instanceof ApiError && (error.status === 0 || error.status >= 500);

export function createBehaviorTracker(options: BehaviorTrackerOptions) {
  const newEventId = options.newEventId ?? (() => crypto.randomUUID());
  const now = options.now ?? (() => new Date());
  const maxAttempts = Math.max(1, options.maxAttempts ?? 2);
  let stopped = false;

  const allowedToSend = (): TrackOutcome | null => {
    if (!options.enabled) return 'skipped_disabled';
    if (stopped || !options.hasConsent()) return 'skipped_no_consent';
    return null;
  };

  /** 이미 만든 이벤트를 (같은 event_id로) 보냅니다. 재전송에도 씁니다. */
  async function send(event: BehaviorEventInput): Promise<TrackOutcome> {
    if (!isAllowedMetadata(event.event_code, event.metadata ?? undefined)) return 'skipped_not_allowed';
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const blocked = allowedToSend();
      if (blocked) return blocked;
      try {
        const result = await options.send(event);
        if (result.status === 'blocked_no_consent') stopped = true;
        return result.status;
      } catch (error) {
        if (!retriable(error) || attempt === maxAttempts) return 'failed';
      }
    }
    return 'failed';
  }

  return {
    /** 승인된 tracking 이벤트 1건을 만들어 보냅니다. 예외를 던지지 않습니다. */
    track<C extends TrackingEventCode>(code: C, metadata?: TrackingMetadata<C>): Promise<TrackOutcome> {
      const blocked = allowedToSend();
      if (blocked) return Promise.resolve(blocked);
      const values: Record<string, MetadataValue> = {};
      for (const [key, value] of Object.entries(metadata ?? {})) if (value !== undefined) values[key] = value as MetadataValue;
      return send({ event_id: newEventId(), event_code: code, event_at: now().toISOString(), metadata: values });
    },
    send,
    /** 동의 철회 직후 호출: 이후 요청을 보내지 않습니다. */
    revoke() { stopped = true; },
    /** 다시 동의했을 때 (hasConsent()도 true여야 보냅니다) */
    resume() { stopped = false; },
  };
}

export type BehaviorTracker = ReturnType<typeof createBehaviorTracker>;
