/**
 * T100 고급 검색 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음.
 * T98 계약(PROPOSED) §3~§5 를 흉내 냅니다: 검증 422, 제목·기업명 검색(%·_ 문자 그대로), 다중 값 OR·조건 AND,
 * 지역 = location_text 첫 단어 별칭(§4), 게시 기간, 안정 정렬, 조건에 묶인 cursor(다르면 400).
 * 시험(JobSearchAdvanced.test.tsx)이 이 Mock 을 T98 수용 사례 JSON 과 대조합니다 — 실제 API(T99)도 같은 JSON 으로 검증됨.
 */
import type { JobPostingPage } from '../api/catalog';
import { ApiError } from '../api/errors';
import {
  EMPLOYMENT_TYPES, MAX_VALUES, POSTED_WITHIN, Q_MAX, REGION_CODES,
  type AdvancedJobQuery, type JobSearchService, type RegionCode,
} from '../api/jobSearch';

const PATH = '/v1/job-postings';
const DAY = 86_400_000;

/** T98 §4 표와 같아야 함(시험이 문서와 대조) */
export const REGION_ALIASES: Record<RegionCode, string[]> = {
  seoul: ['서울'], busan: ['부산'], daegu: ['대구'], incheon: ['인천'], gwangju: ['광주'], daejeon: ['대전'], ulsan: ['울산'],
  sejong: ['세종'], gyeonggi: ['경기'], gangwon: ['강원'], chungbuk: ['충북', '충청북도'], chungnam: ['충남', '충청남도'],
  jeonbuk: ['전북', '전라북도'], jeonnam: ['전남', '전라남도'], gyeongbuk: ['경북', '경상북도'], gyeongnam: ['경남', '경상남도'],
  jeju: ['제주'],
};

export type MockPosting = {
  job_posting_id: string;
  title: string;
  status: 'published' | 'closed' | 'draft';
  company: { company_id: string; name: string };
  job_role: { job_role_id: string; code: string; name: string } | null;
  employment_type: string | null;
  location_text: string | null;
  published_at: string | null;
  expires_at: string | null;
};

export function regionOf(location: string | null): RegionCode | null {
  const token = location?.trim().split(/\s+/)[0];
  if (!token) return null;
  return REGION_CODES.find((code) => REGION_ALIASES[code].some((alias) => token.startsWith(alias))) ?? null;
}

const invalid = () => new ApiError(422, PATH, undefined, 'VALIDATION_FAILED', '입력값을 확인해 주세요.');
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function normalize(query: AdvancedJobQuery) {
  const q = query.q === undefined ? undefined : query.q.split(/\s+/).filter(Boolean).join(' ');
  if (q !== undefined && (q.length < 1 || q.length > Q_MAX)) throw invalid();
  const list = <T extends string>(key: keyof typeof MAX_VALUES, values: T[] | undefined, ok: (v: string) => boolean) => {
    const raw = values ?? [];
    if (raw.length > MAX_VALUES[key] || !raw.every(ok)) throw invalid();
    return [...new Set(raw)].sort();
  };
  const limit = query.limit ?? 20;
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw invalid();
  if (query.posted_within !== undefined && !(POSTED_WITHIN as readonly string[]).includes(query.posted_within)) throw invalid();
  if (query.sort !== undefined && !['-published_at', 'expires_at'].includes(query.sort)) throw invalid();
  return {
    q, limit, posted_within: query.posted_within, include_closed: Boolean(query.include_closed),
    sort: query.sort ?? '-published_at',
    company_id: list('company_id', query.company_id, (v) => UUID.test(v)),
    job_role_id: list('job_role_id', query.job_role_id, (v) => UUID.test(v)),
    employment_type: list('employment_type', query.employment_type, (v) => (EMPLOYMENT_TYPES as readonly string[]).includes(v)),
    region: list('region', query.region, (v) => (REGION_CODES as readonly string[]).includes(v)),
  };
}

export type MockJobSearchOptions = { postings?: MockPosting[]; now?: () => Date; latencyMs?: number };

export function createMockJobSearchService(options: MockJobSearchOptions = {}): JobSearchService & {
  calls: AdvancedJobQuery[]; failNext: () => void;
} {
  const now = options.now ?? (() => new Date());
  const postings = options.postings ?? seedPostings(now());
  const calls: AdvancedJobQuery[] = [];
  let fail = false;
  return {
    calls,
    failNext() { fail = true; },
    async list(query, signal) {
      calls.push(query);
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, options.latencyMs ?? 0);
        signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
      });
      if (fail) { fail = false; throw new ApiError(0, PATH); }
      const n = normalize(query);
      const { limit, ...filters } = n;
      const digest = JSON.stringify(filters);
      const at = now().getTime();
      const time = (v: string | null) => (v === null ? null : Date.parse(v));
      const rows = postings.filter((p) => {
        if (p.status === 'draft') return false;
        const open = p.status === 'published' && (p.expires_at === null || time(p.expires_at)! > at);
        if (!n.include_closed && !open) return false;
        if (n.q) {
          const q = n.q.toLowerCase();
          if (!p.title.toLowerCase().includes(q) && !p.company.name.toLowerCase().includes(q)) return false;
        }
        if (n.company_id.length && !n.company_id.includes(p.company.company_id)) return false;
        if (n.job_role_id.length && !n.job_role_id.includes(p.job_role?.job_role_id ?? '')) return false;
        if (n.employment_type.length && !(n.employment_type as string[]).includes(p.employment_type ?? '')) return false;
        if (n.region.length && !n.region.includes(regionOf(p.location_text) ?? ('' as RegionCode))) return false;
        if (n.posted_within) {
          const days = Number(n.posted_within.slice(0, -1));
          const published = time(p.published_at);
          if (published === null || published < at - days * DAY) return false;
        }
        return true;
      });
      rows.sort((a, b) => {
        if (n.sort === 'expires_at') {
          const ka = time(a.expires_at) ?? Infinity; const kb = time(b.expires_at) ?? Infinity;
          return ka - kb || a.job_posting_id.localeCompare(b.job_posting_id);
        }
        const ka = time(a.published_at) ?? -Infinity; const kb = time(b.published_at) ?? -Infinity;
        return kb - ka || b.job_posting_id.localeCompare(a.job_posting_id);
      });
      let start = 0;
      if (query.cursor) {
        let decoded: { d: string; o: number };
        try { decoded = JSON.parse(atob(query.cursor)) as { d: string; o: number }; } catch { decoded = { d: '', o: 0 }; }
        if (decoded.d !== digest) throw new ApiError(400, PATH, undefined, 'INVALID_CURSOR', '목록 정보가 만료되었습니다. 처음부터 다시 조회해 주세요.');
        start = decoded.o;
      }
      const page = rows.slice(start, start + limit);
      const next = start + limit < rows.length ? btoa(JSON.stringify({ d: digest, o: start + limit })) : null;
      return {
        items: page.map((p) => ({
          job_posting_id: p.job_posting_id, title: p.title,
          status: p.status === 'published' && (p.expires_at === null || time(p.expires_at)! > at) ? 'published' : 'closed',
          company: p.company, job_role: p.job_role,
          employment_type: p.employment_type as JobPostingPage['items'][number]['employment_type'],
          location_text: p.location_text, published_at: p.published_at, expires_at: p.expires_at,
        })),
        next_cursor: next,
      } as JobPostingPage;
    },
  };
}

/** 개발 서버용 합성 공고 36건(실제 기업·공고 아님). */
export function seedPostings(base: Date): MockPosting[] {
  const companies = ['가상테크', '예시소프트', '샘플랩', '데모데이터', '테스트모빌리티', '모의헬스'];
  const roles = [null, { code: 'backend', name: '백엔드 개발자' }, { code: 'frontend', name: '프론트엔드 개발자' },
    { code: 'data', name: '데이터 엔지니어' }];
  const titles = ['백엔드 개발자', '프론트엔드 개발자', '데이터 엔지니어', 'QA 엔지니어', '서버 개발자', '모바일 개발자'];
  const places = ['서울 강남구', '경기 성남시 분당구', '부산 해운대구', '대전 유성구', '충청북도 청주시', '제주 제주시', null, '재택근무'];
  const types = ['full_time', 'contract', 'intern', 'part_time', null];
  const hex = (n: number, prefix: string) => `00000000-0000-4000-8${prefix}-${String(n).padStart(12, '0')}`;
  return Array.from({ length: 36 }, (_, i) => {
    const role = roles[i % roles.length]!;
    const published = new Date(base.getTime() - (i * 37 % 45) * DAY - i * 3_600_000);
    return {
      job_posting_id: hex(i + 1, '100'), title: `${titles[i % titles.length]} (가상 ${i + 1})`,
      status: i % 11 === 10 ? 'closed' : 'published',
      company: { company_id: hex((i % companies.length) + 1, '200'), name: companies[i % companies.length]! },
      job_role: role && { job_role_id: hex(roles.indexOf(role), '300'), ...role },
      employment_type: types[i % types.length]!, location_text: places[i % places.length]!,
      published_at: published.toISOString(),
      expires_at: i % 4 === 0 ? null : new Date(published.getTime() + ((i * 13) % 60 + 1) * DAY).toISOString(),
    };
  });
}
