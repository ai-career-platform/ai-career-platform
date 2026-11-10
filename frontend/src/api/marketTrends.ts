/**
 * T68 채용시장 추세 API (T67 `GET /api/v1/market-trends`, FR-ANL-005, UI-024).
 *
 * 타입은 T67 Backend(PR #174 backend/app/schemas/market_trends.py)와 T65 계약
 * (docs/data/MARKET_METRICS_CONTRACT.md)을 그대로 옮겼습니다. main 의 openapi.yaml `MarketTrend` 는
 * T67 이전 초안(source 가 문자열, unit·job_role·skill 없음)이라 아직 Schemas['MarketTrend'] 를 쓰지 않습니다.
 * #174 가 main 에 들어오면 schema.gen 타입으로 바꾸고 이 수기 타입을 지우세요.
 * 화면은 useApi().marketTrends 로 씁니다. 로그인 토큰과 401 처리는 AuthProvider 의 클라이언트가 맡습니다.
 */
import type { HttpClient } from './http';

export type MarketMetricCode = 'posting_count' | 'skill_demand_share';
export type MarketPeriod = 'day' | 'week' | 'month';
/** count = 건, ratio = 0~1 비율 (T65 계약 §1) */
export type MarketUnit = 'count' | 'ratio';

export type MarketPoint = {
  /** 집계 구간 시작일 (KST, 주=월요일, 월=1일), YYYY-MM-DD */
  date: string;
  value: number;
  lower_bound?: number | null;
  upper_bound?: number | null;
};

export type MarketSource = { code: string; name: string };
export type MarketJobRole = { job_role_id: string; code: string; name: string };
export type MarketSkill = { skill_id: string; code: string; name: string };

export type MarketTrend = {
  metric_code: MarketMetricCode;
  unit: MarketUnit;
  period: MarketPeriod;
  from: string;
  to: string;
  /** 관측값 출처. 관측값이 없으면 null */
  source: MarketSource | null;
  /** null = 전체 시장 */
  job_role: MarketJobRole | null;
  skill: MarketSkill | null;
  /** 관측값 (observed_on 오름차순). 데이터가 없는 구간은 빠져 있습니다(0으로 채우지 않음). */
  observations: MarketPoint[];
  /** 예측값. T68 화면은 쓰지 않습니다(예측은 T69 이후 범위). */
  forecasts: MarketPoint[];
  forecast_model: { model_code: string; version: string; kind: string } | null;
};

export type MarketTrendQuery = {
  metric_code: MarketMetricCode;
  from: string;
  to: string;
  period: MarketPeriod;
  job_role_id?: string | null;
  /** skill_demand_share 일 때 필수 */
  skill_id?: string | null;
  /** 출처 코드. 없으면 관측값이 있는 출처가 하나일 때 서버가 자동 선택(둘 이상이면 422) */
  source?: string | null;
};

export const marketTrendsApi = (http: HttpClient) => ({
  get: (query: MarketTrendQuery, signal?: AbortSignal) =>
    http.request<MarketTrend>('/v1/market-trends', { query, signal }),
});
