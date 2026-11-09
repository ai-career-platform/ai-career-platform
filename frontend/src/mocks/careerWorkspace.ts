import type { MockRequest } from './handlers';

const roles = [
  { job_role_id: '11111111-1111-4111-8111-111111111111', code: 'backend', name: '백엔드 개발자' },
  { job_role_id: '22222222-2222-4222-8222-222222222222', code: 'frontend', name: '프론트엔드 개발자' },
  { job_role_id: '33333333-3333-4333-8333-333333333333', code: 'data', name: '데이터 엔지니어' },
];
let targets = [{ job_role: roles[0], priority: 1 }];
let experiences: unknown[] = [];
let projects: unknown[] = [];
let bookmarks = [
  { job_posting_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', title: '주니어 Backend Engineer', status: 'published', company: { company_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', name: '가상 테크' }, job_role: roles[0], employment_type: 'full_time', location_text: '서울', published_at: null, expires_at: null },
  { job_posting_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', title: 'Frontend Developer', status: 'closed', company: { company_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', name: '샘플 랩' }, job_role: roles[1], employment_type: null, location_text: null, published_at: null, expires_at: null },
];
const now = () => new Date().toISOString();
const id = () => crypto.randomUUID();

export function resolveCareerWorkspaceMock(path: string, request: MockRequest): unknown | null {
  if (path === '/v1/job-roles?limit=100' && request.method === 'GET') return { items: roles, next_cursor: null };
  if (path === '/v1/me/target-roles') {
    if (request.method === 'GET') return targets;
    if (request.method === 'PUT') {
      const items = (request.body as { items: { job_role_id: string; priority: number }[] }).items;
      targets = items.map((item) => ({ job_role: roles.find((role) => role.job_role_id === item.job_role_id)!, priority: item.priority }));
      return targets;
    }
  }
  if (path === '/v1/me/experiences') {
    if (request.method === 'GET') return experiences;
    if (request.method === 'POST') {
      const item = { ...(request.body as object), experience_id: id(), updated_at: now() };
      experiences = [...experiences, item]; return item;
    }
  }
  if (path.startsWith('/v1/me/experiences/') && request.method === 'DELETE') {
    experiences = experiences.filter((x) => (x as { experience_id: string }).experience_id !== path.split('/').at(-1)); return undefined;
  }
  if (path === '/v1/me/projects') {
    if (request.method === 'GET') return projects;
    if (request.method === 'POST') {
      const item = { ...(request.body as object), project_id: id(), skills: [], updated_at: now() };
      projects = [...projects, item]; return item;
    }
  }
  if (path.startsWith('/v1/me/projects/') && request.method === 'DELETE') {
    projects = projects.filter((x) => (x as { project_id: string }).project_id !== path.split('/').at(-1)); return undefined;
  }
  if (path === '/v1/me/bookmarks' && request.method === 'GET') return { items: bookmarks, next_cursor: null };
  if (path.startsWith('/v1/me/bookmarks/') && request.method === 'DELETE') {
    bookmarks = bookmarks.filter((x) => x.job_posting_id !== path.split('/').at(-1)); return undefined;
  }
  return null;
}
