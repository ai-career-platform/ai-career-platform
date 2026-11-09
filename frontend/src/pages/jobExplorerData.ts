/** T23 fixed synthetic fixture; no T17 network calls or actual user skill data. */
export type JobSkill = { code: string; name: string; requiredLevel: number };
export type JobRole = {
  id: string; code: string; name: string; category: string;
  description: string; skills: readonly JobSkill[];
};
export type JobSort = 'name' | 'category';

export const demoJobRoles: readonly JobRole[] = [
  { id: 'demo-backend', code: 'backend', name: '백엔드 개발자', category: '개발',
    description: '서버와 API, 서비스의 데이터 흐름을 개발합니다.',
    skills: [{ code: 'python', name: 'Python', requiredLevel: 3 }, { code: 'sql', name: 'SQL', requiredLevel: 3 }, { code: 'api', name: 'REST API', requiredLevel: 3 }] },
  { id: 'demo-frontend', code: 'frontend', name: '프론트엔드 개발자', category: '개발',
    description: '웹 인터페이스와 사용자 상호작용을 개발합니다.',
    skills: [{ code: 'javascript', name: 'JavaScript', requiredLevel: 3 }, { code: 'react', name: 'React', requiredLevel: 3 }, { code: 'html', name: 'HTML', requiredLevel: 2 }] },
  { id: 'demo-analyst', code: 'analyst', name: '데이터 분석가', category: '데이터',
    description: '데이터를 분석하고 시각화해 의사결정을 돕습니다.',
    skills: [{ code: 'python', name: 'Python', requiredLevel: 3 }, { code: 'sql', name: 'SQL', requiredLevel: 3 }, { code: 'viz', name: '시각화', requiredLevel: 3 }] },
  { id: 'demo-engineer', code: 'data-engineer', name: '데이터 엔지니어', category: '데이터',
    description: '안정적인 데이터 수집·처리 파이프라인을 만듭니다.',
    skills: [{ code: 'python', name: 'Python', requiredLevel: 3 }, { code: 'sql', name: 'SQL', requiredLevel: 4 }, { code: 'etl', name: 'ETL', requiredLevel: 3 }] },
  { id: 'demo-ml', code: 'ml-engineer', name: '머신러닝 엔지니어', category: 'AI',
    description: '머신러닝 모델을 학습·평가하고 제품에 적용합니다.',
    skills: [{ code: 'python', name: 'Python', requiredLevel: 4 }, { code: 'ml', name: '머신러닝', requiredLevel: 4 }, { code: 'sql', name: 'SQL', requiredLevel: 2 }] },
  { id: 'demo-designer', code: 'ux-designer', name: 'UX 디자이너', category: '디자인',
    description: '사용자 경험을 조사하고 화면과 흐름을 설계합니다.',
    skills: [{ code: 'research', name: '사용자 리서치', requiredLevel: 3 }, { code: 'prototype', name: '프로토타입', requiredLevel: 3 }] },
  { id: 'demo-pm', code: 'service-pm', name: '서비스 기획자', category: '기획',
    description: '사용자 요구와 제품 목표를 연결합니다.',
    skills: [{ code: 'planning', name: '서비스 기획', requiredLevel: 3 }, { code: 'analytics', name: '데이터 분석', requiredLevel: 2 }] },
  { id: 'demo-cloud', code: 'cloud-engineer', name: '클라우드 엔지니어', category: '개발',
    description: '클라우드 인프라와 배포·운영 환경을 개선합니다.',
    skills: [{ code: 'cloud', name: '클라우드', requiredLevel: 3 }, { code: 'linux', name: 'Linux', requiredLevel: 3 }] },
];

export function loadMockJobRoles(): Promise<readonly JobRole[]> {
  return Promise.resolve(demoJobRoles);
}
const collator = new Intl.Collator('ko', { sensitivity: 'base', numeric: true });

export function filterJobRoles(
  roles: readonly JobRole[], query: string, category: string, sort: JobSort,
): JobRole[] {
  if (!Array.isArray(roles) || typeof query !== 'string' ||
      typeof category !== 'string' || !['name', 'category'].includes(sort)) {
    throw new TypeError('Invalid job explorer inputs');
  }
  const term = query.trim().toLocaleLowerCase('ko');
  const result = roles.filter((role) =>
    (category === '전체' || role.category === category) &&
    (!term || [role.name, role.code, role.category,
      ...role.skills.flatMap((skill) => [skill.name, skill.code])]
      .join(' ').toLocaleLowerCase('ko').includes(term)),
  );
  return result.sort((a, b) =>
    (sort === 'category' ? collator.compare(a.category, b.category) : 0) ||
    collator.compare(a.name, b.name) || collator.compare(a.code, b.code));
}

export function pageJobRoles<T>(rows: readonly T[], page: number, size = 4) {
  if (!Array.isArray(rows) || !Number.isInteger(page) || page < 1 ||
      !Number.isInteger(size) || size < 1) throw new RangeError('Invalid page');
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const current = Math.min(page, pages);
  return { items: rows.slice((current - 1) * size, current * size), current, pages };
}
