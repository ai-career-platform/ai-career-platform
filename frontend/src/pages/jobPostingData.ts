/** T24 synthetic fixtures only, not actual T18 listings or verified external links. */
export type JobPostingStatus = 'published' | 'closed' | 'draft';
export type PostingFilterStatus = 'open' | 'closed' | 'all';
export type PostingSort = 'recent' | 'deadline';
export type DemoPosting = {
  id: string;
  title: string;
  companyId: string;
  companyName: string;
  companyDescription: string;
  role: string;
  location: string;
  employment: string;
  status: JobPostingStatus;
  publishedAt: string | null;
  expiresAt: string | null;
  description: string;
  requiredSkills: readonly string[];
  source: 'synthetic_seed';
  sourceUrl: null;
};

/** Explicit date to make mock screenshots/tests reproducible. T18 must use approved server policy. */
export const DEMO_REFERENCE_DATE = '2026-11-09';

export const demoPostings: readonly DemoPosting[] = [
  {
    id: 'demo-post-01', title: '프론트엔드 개발자 채용', companyId: 'demo-nova',
    companyName: '노바랩', companyDescription: '디지털 서비스를 개발하는 가상 기업입니다.',
    role: '프론트엔드 개발자', location: '서울', employment: '정규직',
    status: 'published', publishedAt: '2026-11-01T00:00:00Z', expiresAt: '2026-12-10T00:00:00Z',
    description: '접근성을 고려한 웹 애플리케이션 UI를 개발하는 가상 채용공고입니다.',
    requiredSkills: ['React', 'TypeScript', 'HTML'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-02', title: '주니어 데이터 분석가', companyId: 'demo-forest',
    companyName: '데이터포레스트', companyDescription: '데이터 분석 서비스를 연구하는 가상 기업입니다.',
    role: '데이터 분석가', location: '판교', employment: '정규직',
    status: 'published', publishedAt: '2026-11-04T00:00:00Z', expiresAt: '2026-11-30T00:00:00Z',
    description: 'SQL과 Python으로 가상 데이터를 분석하는 직무입니다.',
    requiredSkills: ['SQL', 'Python', '시각화'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-03', title: '백엔드 API 개발자', companyId: 'demo-example',
    companyName: '예시테크', companyDescription: '개발 도구를 만드는 가상 기업입니다.',
    role: '백엔드 개발자', location: '서울', employment: '계약직',
    status: 'published', publishedAt: '2026-11-06T00:00:00Z', expiresAt: null,
    description: '서버와 API를 구현하는 가상 채용공고입니다.',
    requiredSkills: ['Python', 'REST API', 'SQL'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-04', title: '프로덕트 디자이너', companyId: 'demo-move',
    companyName: '스튜디오 모브', companyDescription: '사용자 경험을 연구하는 가상 기업입니다.',
    role: 'UX 디자이너', location: '서울', employment: '정규직',
    status: 'published', publishedAt: '2026-10-15T00:00:00Z', expiresAt: '2026-11-01T00:00:00Z',
    description: '프로토타입과 화면 구성에 참여하는 가상 채용공고입니다.',
    requiredSkills: ['Figma', '프로토타이핑'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-05', title: '서비스 기획자 모집', companyId: 'demo-move',
    companyName: '스튜디오 모브', companyDescription: '사용자 경험을 연구하는 가상 기업입니다.',
    role: '서비스 기획자', location: '원격', employment: '정규직',
    status: 'closed', publishedAt: '2026-10-20T00:00:00Z', expiresAt: '2026-10-31T00:00:00Z',
    description: '서비스 요구사항을 정리하는 가상 채용공고입니다.',
    requiredSkills: ['기획', '커뮤니케이션'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-06', title: '클라우드 운영 엔지니어', companyId: 'demo-nova',
    companyName: '노바랩', companyDescription: '디지털 서비스를 개발하는 가상 기업입니다.',
    role: '클라우드 엔지니어', location: '서울', employment: '정규직',
    status: 'published', publishedAt: '2026-11-07T00:00:00Z', expiresAt: '2026-11-28T00:00:00Z',
    description: '클라우드 서비스의 운영과 배포를 지원하는 가상 채용공고입니다.',
    requiredSkills: ['AWS', 'Linux', '자동화'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-07', title: '데이터 파이프라인 개발', companyId: 'demo-forest',
    companyName: '데이터포레스트', companyDescription: '데이터 분석 서비스를 연구하는 가상 기업입니다.',
    role: '데이터 엔지니어', location: '판교', employment: '정규직',
    status: 'published', publishedAt: '2026-11-02T00:00:00Z', expiresAt: '2026-12-03T00:00:00Z',
    description: '가상 데이터의 수집과 적재 파이프라인을 개발합니다.',
    requiredSkills: ['SQL', 'Python', 'ETL'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-08', title: 'AI 엔지니어 인턴', companyId: 'demo-example',
    companyName: '예시테크', companyDescription: '개발 도구를 만드는 가상 기업입니다.',
    role: '머신러닝 엔지니어', location: '서울', employment: '인턴',
    status: 'published', publishedAt: '2026-11-05T00:00:00Z', expiresAt: '2026-11-15T00:00:00Z',
    description: '가상 모델 평가 업무를 지원하는 인턴십입니다.',
    requiredSkills: ['Python', '머신러닝'], source: 'synthetic_seed', sourceUrl: null,
  },
  {
    id: 'demo-post-hidden', title: '미게시 가상 채용', companyId: 'demo-nova',
    companyName: '노바랩', companyDescription: '디지털 서비스를 개발하는 가상 기업입니다.',
    role: '백엔드 개발자', location: '서울', employment: '정규직',
    status: 'draft', publishedAt: null, expiresAt: null,
    description: '미게시 공고는 UI에 노출하지 않아야 합니다.',
    requiredSkills: ['Python'], source: 'synthetic_seed', sourceUrl: null,
  },
];

export function loadMockPostings(): Promise<readonly DemoPosting[]> {
  return Promise.resolve(demoPostings);
}

export function isClosed(posting: DemoPosting, asOf: string): boolean {
  return posting.status === 'closed' ||
    (posting.status === 'published' && posting.expiresAt !== null &&
      posting.expiresAt.slice(0, 10) < asOf);
}

export function filterDemoPostings(
  postings: readonly DemoPosting[],
  filters: {
    query: string; companyId: string; role: string; status: PostingFilterStatus;
    order: PostingSort; asOf: string;
  },
): DemoPosting[] {
  if (!Array.isArray(postings) || typeof filters.query !== 'string' ||
      !['open', 'closed', 'all'].includes(filters.status) ||
      !['recent', 'deadline'].includes(filters.order)) {
    throw new TypeError('Invalid T24 mock search input');
  }
  const query = filters.query.trim().toLocaleLowerCase('ko');
  return postings.filter((posting) => {
    if (posting.status === 'draft') return false;
    const closed = isClosed(posting, filters.asOf);
    if (filters.status === 'open' && closed) return false;
    if (filters.status === 'closed' && !closed) return false;
    if (filters.companyId && posting.companyId !== filters.companyId) return false;
    if (filters.role && posting.role !== filters.role) return false;
    return !query || [
      posting.title, posting.companyName, posting.role, ...posting.requiredSkills,
    ].join(' ').toLocaleLowerCase('ko').includes(query);
  }).sort((a, b) => {
    if (filters.order === 'deadline') {
      // Listings without a deadline stay after dated listings.
      return (a.expiresAt === null ? 1 : b.expiresAt === null ? -1 :
        a.expiresAt.localeCompare(b.expiresAt)) || a.id.localeCompare(b.id);
    }
    return (b.publishedAt ?? '').localeCompare(a.publishedAt ?? '') || a.id.localeCompare(b.id);
  });
}

export function pageDemoPostings<T>(items: readonly T[], page: number, size = 4):
  { items: T[]; current: number; pages: number } {
  if (!Array.isArray(items) || !Number.isInteger(page) || page < 1 ||
      !Number.isInteger(size) || size < 1) throw new RangeError('Invalid page');
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(page, pages);
  return { items: items.slice((current - 1) * size, current * size), current, pages };
}
