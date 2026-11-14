/**
 * 채용공고 고급 검색 (T100). 계약: docs/search/T98_ADVANCED_SEARCH_CONTRACT.md — **PROPOSED, docs/api/openapi.yaml 에 없음**.
 * 서버(T99)는 `JOB_SEARCH_ADVANCED=true` 일 때만 이 매개변수를 받습니다(기본 꺼짐). 화면은 `VITE_JOB_SEARCH_ADVANCED_UI`(기본 꺼짐)
 * 뒤에 있으며, Mock 모드가 아니면 아래 HTTP 어댑터로 실제 API 를 부릅니다. 서버 플래그가 꺼져 있으면 T18 목록이 응답하므로
 * 고급 조건(employment_type·region·posted_within, company_id·job_role_id 다중 값)은 무시될 뿐 화면은 깨지지 않습니다.
 * 공개 범위(게시 중·만료 전 공고만, 초안 제외)는 서버가 정합니다.
 */
import type { HttpClient } from './http';
import type { JobPostingPage } from './catalog';

export const EMPLOYMENT_TYPES = ['full_time', 'contract', 'intern', 'part_time'] as const;
export type EmploymentType = (typeof EMPLOYMENT_TYPES)[number];

/** T98 §4 순서(시·도 행정 순). 라벨은 화면 표시용 */
export const REGIONS = [
  ['seoul', '서울'], ['busan', '부산'], ['daegu', '대구'], ['incheon', '인천'], ['gwangju', '광주'], ['daejeon', '대전'],
  ['ulsan', '울산'], ['sejong', '세종'], ['gyeonggi', '경기'], ['gangwon', '강원'], ['chungbuk', '충북'],
  ['chungnam', '충남'], ['jeonbuk', '전북'], ['jeonnam', '전남'], ['gyeongbuk', '경북'], ['gyeongnam', '경남'],
  ['jeju', '제주'],
] as const;
export type RegionCode = (typeof REGIONS)[number][0];
export const REGION_CODES = REGIONS.map(([code]) => code) as RegionCode[];

export const POSTED_WITHIN = ['1d', '3d', '7d', '30d'] as const;
export type PostedWithin = (typeof POSTED_WITHIN)[number];
export const POSTED_WITHIN_LABELS: Record<PostedWithin, string> = {
  '1d': '1일 이내', '3d': '3일 이내', '7d': '1주 이내', '30d': '30일 이내',
};
export type JobSort = '-published_at' | 'expires_at';

/** T98 §3 상한 */
export const MAX_VALUES = { company_id: 10, job_role_id: 10, employment_type: 4, region: 5 } as const;
export const Q_MAX = 100;

export type AdvancedJobQuery = {
  q?: string;
  company_id?: string[];
  job_role_id?: string[];
  employment_type?: EmploymentType[];
  region?: RegionCode[];
  posted_within?: PostedWithin;
  include_closed?: boolean;
  sort?: JobSort;
  limit?: number;
  cursor?: string | null;
};

export interface JobSearchService {
  list(query: AdvancedJobQuery, signal?: AbortSignal): Promise<JobPostingPage>;
}

/** 실제 API 어댑터(createApi 의 `jobSearch`): 같은 경로에 배열은 키를 반복해 보냄(`region=a&region=b`). */
export function createHttpJobSearchService(http: HttpClient): JobSearchService {
  return {
    list: (query, signal) => http.request<JobPostingPage>('/v1/job-postings', { query: { ...query }, signal }),
  };
}
