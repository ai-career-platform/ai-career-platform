/**
 * T34 개발용 가상 데이터 — 기술 목록(T17)과 내 보유 기술(T33).
 * DB·실제 계정·영구 저장 없음. 검증 규칙은 Backend T33과 같게 맞춥니다(Mock 성공은 실제 서비스 PASS가 아님).
 */
import { ApiError } from '../api/errors';
import { MAX_SKILLS, SEARCH_MIN_LENGTH, type Skill, type UserSkill } from '../api/skills';
import type { MockRequest } from './handlers';

const catalog: (Skill & { is_active: boolean })[] = [
  ['PYTHON', 'Python'], ['PYTEST', 'pytest'], ['PYTORCH', 'PyTorch'], ['JAVA', 'Java'],
  ['JAVASCRIPT', 'JavaScript'], ['TYPESCRIPT', 'TypeScript'], ['REACT', 'React'], ['SQL', 'SQL'],
  ['POSTGRESQL', 'PostgreSQL'], ['DOCKER', 'Docker'], ['KUBERNETES', 'Kubernetes'], ['GIT', 'Git'],
  ['AGILE_SCRUM', '애자일/스크럼'], ['COBOL', 'COBOL'],
].map(([code, name], i) => ({
  skill_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, '0')}`,
  code: code!, name: name!, is_active: code !== 'COBOL',
}));

const states = new Map<string, Map<string, number | null>>();
export function resetSkillsMocks() { states.clear(); }
export const mockSkillCatalog = catalog;

const fail = (status: number, code: string): never => { throw new ApiError(status, '', undefined, code); };
const toSkill = ({ skill_id, code, name }: Skill): Skill => ({ skill_id, code, name });

function listOf(owned: Map<string, number | null>): UserSkill[] {
  return [...owned].map(([id, proficiency]) => ({ skill: toSkill(catalog.find(s => s.skill_id === id)!), proficiency }))
    .sort((a, b) => a.skill.name.localeCompare(b.skill.name) || a.skill.skill_id.localeCompare(b.skill.skill_id)) as UserSkill[];
}

export function resolveSkillsMock(path: string, request: MockRequest, userKey: string | null): unknown {
  const [pathname, query = ''] = path.split('?');
  if (pathname === '/v1/skills' && request.method === 'GET') {
    const params = new URLSearchParams(query);
    const q = (params.get('q') ?? '').trim().toLowerCase();
    const limit = Number(params.get('limit') ?? 20);
    if (q.length < SEARCH_MIN_LENGTH) return fail(422, 'VALIDATION_FAILED');
    const hits = catalog.filter(s => s.is_active && s.name.toLowerCase().includes(q))
      .sort((a, b) => Number(!a.name.toLowerCase().startsWith(q)) - Number(!b.name.toLowerCase().startsWith(q))
        || a.name.localeCompare(b.name));
    return { items: hits.slice(0, limit).map(toSkill) };
  }
  if (pathname !== '/v1/me/skills') return null;
  if (!userKey) return fail(401, 'UNAUTHENTICATED');
  const owned = states.get(userKey) ?? new Map<string, number | null>();
  states.set(userKey, owned);
  if (request.method === 'GET') return listOf(owned);
  if (request.method !== 'PUT') return null;

  const items = (request.body as { items?: { skill_id?: string; proficiency?: unknown }[] })?.items;
  if (!Array.isArray(items) || items.length > MAX_SKILLS) return fail(422, 'VALIDATION_FAILED');
  const next = new Map<string, number | null>();
  for (const item of items) {
    const p = item.proficiency ?? null;
    if (typeof item.skill_id !== 'string' || (p !== null && !(Number.isInteger(p) && (p as number) >= 1 && (p as number) <= 5))) {
      return fail(422, 'VALIDATION_FAILED');
    }
    if (next.has(item.skill_id)) return fail(422, 'DUPLICATE_SKILL');
    const skill = catalog.find(s => s.skill_id === item.skill_id);
    if (!skill || (!skill.is_active && !owned.has(skill.skill_id))) return fail(422, 'VALIDATION_FAILED');
    next.set(item.skill_id, p as number | null);
  }
  owned.clear();
  next.forEach((v, k) => owned.set(k, v));
  return listOf(owned);
}
