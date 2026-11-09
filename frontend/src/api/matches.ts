/**
 * 적합도 API (T41, FR-ANL-001). 경로와 타입은 이 파일에만 둡니다. 화면은 createApi(http).matches 로 씁니다.
 * - POST /v1/matches                 → Match (201, 공고 또는 직무 하나)
 * - GET  /v1/matches/{match_id}      → Match (본인 결과만, 다른 사람 결과는 404)
 *
 * 점수는 규칙 기반 설명 점수(0~100)이며 합격 확률·백분위가 아닙니다(`score_is_probability: false`).
 */
import { ApiError } from './errors';
import type { HttpClient } from './http';
import type { BodyOf, ResponseOf } from './schema';

export type Match = ResponseOf<'getMatch'>;
export type MatchRequest = BodyOf<'createMatch'>;

const id = (value: string) => encodeURIComponent(value);

export const matchesApi = (http: HttpClient) => ({
  create: (body: MatchRequest) => http.request<Match>('/v1/matches', { method: 'POST', body }),
  get: (matchId: string, signal?: AbortSignal) => http.request<Match>(`/v1/matches/${id(matchId)}`, { signal }),
});

export type MatchError = { message: string; needsSkills: boolean };

/** 계산 요청 실패를 화면 문구로. 400 NO_USER_SKILLS 는 보유 기술 화면으로 안내합니다. */
export function matchErrorMessage(error: unknown): MatchError {
  if (error instanceof ApiError) {
    if (error.code === 'NO_USER_SKILLS') {
      return { message: '등록된 보유 기술이 없어 적합도를 계산할 수 없습니다.', needsSkills: true };
    }
    if (error.status === 0) return { message: '서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.', needsSkills: false };
    if (error.status === 404) return { message: '공개된 공고·직무가 아니어서 적합도를 계산할 수 없습니다.', needsSkills: false };
    if (error.status === 503) {
      return { message: '적합도 계산 기준이 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.', needsSkills: false };
    }
  }
  return { message: '적합도를 계산하지 못했습니다. 잠시 후 다시 시도해 주세요.', needsSkills: false };
}

/** 분석 시점(UTC ISO)을 한국 시각으로. 값이 잘못되면 '미상'. */
export function formatEvaluatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '미상';
  return date.toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

/** 점수 표기: 소수 둘째 자리까지, 뒤의 0은 뺍니다(62.5, 100). 백분율 기호(%)를 쓰지 않습니다. */
export function formatScore(score: number): string {
  return String(Math.round(score * 100) / 100);
}
