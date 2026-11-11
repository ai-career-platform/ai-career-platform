/**
 * 고급 검색 화면의 URL 상태 (T100, T98 §6).
 * - URL 쿼리 이름 = API 쿼리 이름. 같은 URL 을 열면 같은 조건 → 같은 결과(공유·뒤로가기).
 * - 화면이 모르는 키·값은 버림(사용자 ID·이메일 등이 링크에 남지 않음). 개수 상한은 앞에서부터 자름.
 * - 기본값(최신순·모집 중만)과 cursor 는 URL 에 쓰지 않음. 키 순서를 고정해 같은 조건은 같은 문자열.
 * - 예전 링크 이름(company·role·closed·order)도 읽음.
 */
import {
  EMPLOYMENT_TYPES, MAX_VALUES, POSTED_WITHIN, Q_MAX, REGION_CODES,
  type AdvancedJobQuery, type EmploymentType, type JobSort, type PostedWithin, type RegionCode,
} from '../api/jobSearch';
import { uuidOrEmpty } from './postingFormat';

export type SearchState = {
  q: string;
  company_id: string[];
  job_role_id: string[];
  employment_type: EmploymentType[];
  region: RegionCode[];
  posted_within: PostedWithin | '';
  include_closed: boolean;
  sort: JobSort;
};

export const EMPTY_STATE: SearchState = {
  q: '', company_id: [], job_role_id: [], employment_type: [], region: [], posted_within: '', include_closed: false,
  sort: '-published_at',
};

function pick<T extends string>(values: string[], allowed: readonly T[], limit: number): T[] {
  const set = new Set(values.filter((v): v is T => (allowed as readonly string[]).includes(v)));
  return allowed.filter((v) => set.has(v)).slice(0, limit);       // 허용 목록 순서로 정렬 → 순서 무관
}

function uuids(values: string[], limit: number): string[] {
  return [...new Set(values.map((v) => uuidOrEmpty(v)).filter(Boolean))].sort().slice(0, limit);
}

export const normalizeQ = (value: string) => value.split(/\s+/).filter(Boolean).join(' ').slice(0, Q_MAX);

export function parseSearch(params: URLSearchParams): SearchState {
  const all = (key: string, legacy?: string) => [...params.getAll(key), ...(legacy ? params.getAll(legacy) : [])];
  const posted = params.get('posted_within') ?? '';
  return {
    q: normalizeQ(params.get('q') ?? ''),
    company_id: uuids(all('company_id', 'company'), MAX_VALUES.company_id),
    job_role_id: uuids(all('job_role_id', 'role'), MAX_VALUES.job_role_id),
    employment_type: pick(all('employment_type'), EMPLOYMENT_TYPES, MAX_VALUES.employment_type),
    region: pick(all('region'), REGION_CODES, MAX_VALUES.region),
    posted_within: (POSTED_WITHIN as readonly string[]).includes(posted) ? posted as PostedWithin : '',
    include_closed: params.get('include_closed') === 'true' || params.get('closed') === '1',
    sort: params.get('sort') === 'expires_at' || params.get('order') === 'expires' ? 'expires_at' : '-published_at',
  };
}

export function serializeSearch(state: SearchState): URLSearchParams {
  const out = new URLSearchParams();
  if (state.q) out.set('q', state.q);
  for (const key of ['company_id', 'job_role_id', 'employment_type', 'region'] as const) {
    for (const value of state[key]) out.append(key, value);
  }
  if (state.posted_within) out.set('posted_within', state.posted_within);
  if (state.include_closed) out.set('include_closed', 'true');
  if (state.sort !== '-published_at') out.set('sort', state.sort);
  return out;
}

/** 다시 읽어도 같은 상태가 되도록 정규화(URL → 상태 → URL 이 항등). */
export const normalizeSearch = (state: SearchState) => parseSearch(serializeSearch(state));

export function toApiQuery(state: SearchState, limit: number, cursor: string | null): AdvancedJobQuery {
  return {
    ...(state.q ? { q: state.q } : {}),
    ...(state.company_id.length ? { company_id: state.company_id } : {}),
    ...(state.job_role_id.length ? { job_role_id: state.job_role_id } : {}),
    ...(state.employment_type.length ? { employment_type: state.employment_type } : {}),
    ...(state.region.length ? { region: state.region } : {}),
    ...(state.posted_within ? { posted_within: state.posted_within } : {}),
    include_closed: state.include_closed, sort: state.sort, limit, cursor,
  };
}

export const hasAnyFilter = (state: SearchState) =>
  Boolean(state.q || state.company_id.length || state.job_role_id.length || state.employment_type.length
    || state.region.length || state.posted_within || state.include_closed);
