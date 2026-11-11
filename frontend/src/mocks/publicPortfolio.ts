/**
 * T130 공개 포트폴리오 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음. T129 서버 규칙을 흉내 냅니다.
 * - 비공개 기본, 선택을 바꾸면 동의가 풀림(기존 링크 404), 확인 전에는 링크를 만들 수 없음(409).
 * - 링크: 기본 30일·최대 90일·활성 3개, 토큰은 만들 때 한 번만 돌려줌. 만료·회수·철회·없는 링크는 같은 404.
 * - 공개 화면은 **현재 데이터**를 선택한 것만 그림(원본을 바꾸면 바로 반영, 새 항목은 비공개).
 * 사용자 ID 는 Mock 로그인과 같이 이메일입니다.
 */
import { ApiError } from '../api/errors';
import {
  MAX_ACTIVE_LINKS, PUBLISHABLE, type CreatedLink, type OwnItems, type PortfolioService, type PublicPortfolioReader,
  type PublicProfile, type PublishableField, type Selection, type ShareLink,
} from '../api/publicPortfolio';

const DAY = 86_400_000;
const PATH = '/v1/me/public-profile';

type Exp = { id: string; organization: string; title: string; start: string | null; end: string | null; description: string | null };
type Proj = { id: string; title: string; summary: string | null; start: string | null; end: string | null };
type Profile = { display_name: string; headline: string | null; bio: string | null; location_text: string | null;
  email: string; experiences: Exp[]; projects: Proj[]; skills: [string, number | null][]; target_roles: string[] };
type LinkRow = ShareLink & { user: string; token: string; expires: number };

export type MockPortfolioOptions = { now?: () => Date; latencyMs?: number };
type Failure = 'load' | 'mutate' | 'view';

function seedProfile(user: string): Profile {
  return {
    display_name: user === 'admin@example.com' ? '운영 관리자' : '일반 사용자', headline: '백엔드 개발자 (가상)',
    bio: '연락처 010-0000-0000 같은 정보는 공개하지 마세요 (가상 문장)', location_text: '서울 강남구 (가상)', email: user,
    experiences: [
      { id: 'exp-1', organization: '가상테크', title: '백엔드 개발자', start: '2023-03', end: '2025-01', description: 'API 개발 (가상)' },
      { id: 'exp-2', organization: '비공개로 둘 회사', title: '인턴', start: '2022-01', end: null, description: null },
    ],
    projects: [{ id: 'proj-1', title: '추천 시스템 (가상)', summary: '협업 필터링', start: '2024-01', end: null }],
    skills: [['Python', 4], ['SQL', 3]], target_roles: ['백엔드 개발자'],
  };
}

export function createMockPortfolioBackend(options: MockPortfolioOptions = {}) {
  const now = options.now ?? (() => new Date());
  const profiles = new Map<string, Profile>();
  const selections = new Map<string, Selection>();
  const links: LinkRow[] = [];
  let seq = 0;
  let failures: Failure[] = [];

  const profile = (user: string) => {
    let p = profiles.get(user);
    if (!p) { p = seedProfile(user); profiles.set(user, p); }
    return p;
  };
  const selection = (user: string): Selection =>
    selections.get(user) ?? { fields: [], experience_ids: [], project_ids: [], alias: null, version: 1, consented: false };
  const wait = (signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, options.latencyMs ?? 0);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
  });
  function maybeFail(kind: Failure) {
    if (failures[0] !== kind) return;
    failures = failures.slice(1);
    throw new ApiError(0, PATH);
  }
  const err = (status: number, code: string, message: string) => new ApiError(status, PATH, undefined, code, message);
  const notFound = () => err(404, 'NOT_FOUND', '요청한 정보를 찾을 수 없습니다.');
  const conflict = () => err(409, 'CONFLICT', '현재 상태에서는 처리할 수 없습니다.');
  const token = () => `pf${Array.from({ length: 5 }, () => Math.random().toString(36).slice(2, 11)).join('')}`.padEnd(44, 'z');
  const toLink = ({ user: _u, token: _t, expires: _e, ...rest }: LinkRow): ShareLink => rest;

  function render(user: string): PublicProfile {
    const p = profile(user);
    const s = selection(user);
    const f = new Set<PublishableField>(s.fields);
    const out: PublicProfile = {};
    if (f.has('display_name')) out.display_name = s.alias ?? p.display_name;
    if (f.has('headline') && p.headline) out.headline = p.headline;
    if (f.has('bio') && p.bio) out.bio = p.bio;
    if (f.has('location_text') && p.location_text) out.location_text = p.location_text;
    const ef = ['organization', 'title', 'period', 'description'].filter((k) => f.has(`experience.${k}` as PublishableField));
    if (ef.length) {
      out.experiences = p.experiences.filter((e) => s.experience_ids.includes(e.id)).map((e) => ({
        ...(ef.includes('organization') && { organization: e.organization }), ...(ef.includes('title') && { title: e.title }),
        ...(ef.includes('period') && { period: { start: e.start, end: e.end } }),
        ...(ef.includes('description') && e.description ? { description: e.description } : {}),
      }));
    }
    const pf = ['title', 'summary', 'period'].filter((k) => f.has(`project.${k}` as PublishableField));
    if (pf.length) {
      out.projects = p.projects.filter((x) => s.project_ids.includes(x.id)).map((x) => ({
        ...(pf.includes('title') && { title: x.title }), ...(pf.includes('summary') && x.summary ? { summary: x.summary } : {}),
        ...(pf.includes('period') && { period: { start: x.start, end: x.end } }),
      }));
    }
    if (f.has('skills')) out.skills = p.skills.map(([name, proficiency]) => ({ name, proficiency }));
    if (f.has('target_roles')) out.target_roles = [...p.target_roles];
    return out;
  }

  const reader: PublicPortfolioReader = {
    async view(tokenValue, signal) {
      await wait(signal); maybeFail('view');
      const row = links.find((l) => l.token === tokenValue);
      if (!row || row.revoked || row.expires <= now().getTime() || !selection(row.user).consented) throw notFound();
      row.views += 1;
      return { ...render(row.user), shared_until: row.expires_at };
    },
  };

  return {
    failNext(...kinds: Failure[]) { failures = [...failures, ...kinds]; },
    reader,
    /** 시험·개발용: 원본 프로필을 바꾸면 공개 화면에 바로 반영되는지 확인 */
    editProfile(user: string, change: (p: Profile) => void) { change(profile(user)); },
    serviceFor(user: string): PortfolioService {
      return {
        async settings(signal) {
          await wait(signal); maybeFail('load');
          return { selection: structuredClone(selection(user)),
            links: links.filter((l) => l.user === user).map(toLink).reverse() };
        },
        async ownItems(signal): Promise<OwnItems> {
          await wait(signal); maybeFail('load');
          const p = profile(user);
          return { experiences: p.experiences.map((e) => ({ id: e.id, label: `${e.organization} · ${e.title}` })),
            projects: p.projects.map((x) => ({ id: x.id, label: x.title })) };
        },
        async updateSelection(body) {
          await wait(); maybeFail('mutate');
          const current = selection(user);
          if (current.version !== body.version) throw conflict();
          if (body.fields.some((f) => !(PUBLISHABLE as readonly string[]).includes(f))) throw err(422, 'VALIDATION_FAILED', '입력값을 확인해 주세요.');
          const p = profile(user);
          if (!body.experience_ids.every((id) => p.experiences.some((e) => e.id === id))
            || !body.project_ids.every((id) => p.projects.some((x) => x.id === id))) throw notFound();
          const next: Selection = { ...body, alias: body.alias?.trim() || null, version: current.version + 1, consented: false };
          selections.set(user, next);
          return structuredClone(next);
        },
        async preview(signal) { await wait(signal); maybeFail('load'); return render(user); },
        async confirm(version) {
          await wait(); maybeFail('mutate');
          const current = selection(user);
          if (current.version !== version) throw conflict();
          if (!current.fields.length) throw err(422, 'VALIDATION_FAILED', '공개할 항목을 고르세요.');
          const next = { ...current, consented: true };
          selections.set(user, next);
          return structuredClone(next);
        },
        async withdraw() {
          await wait(); maybeFail('mutate');
          const current = selection(user);
          selections.set(user, { fields: [], experience_ids: [], project_ids: [], alias: null, version: current.version + 1, consented: false });
          for (const l of links) if (l.user === user) l.revoked = true;
        },
        async createLink(ttlDays): Promise<CreatedLink> {
          await wait(); maybeFail('mutate');
          if (!Number.isInteger(ttlDays) || ttlDays < 1 || ttlDays > 90) throw err(422, 'VALIDATION_FAILED', '기간을 확인해 주세요.');
          if (!selection(user).consented) throw conflict();
          const t = now().getTime();
          if (links.filter((l) => l.user === user && !l.revoked && l.expires > t).length >= MAX_ACTIVE_LINKS) throw conflict();
          const row: LinkRow = { link_id: `link-${++seq}`, user, token: token(), created_at: new Date(t).toISOString(),
            expires: t + ttlDays * DAY, expires_at: new Date(t + ttlDays * DAY).toISOString(), revoked: false, views: 0 };
          links.push(row);
          return { ...toLink(row), url: `/p/${row.token}`, notice: '이 주소는 지금 한 번만 보여 줍니다.' };
        },
        async revokeLink(linkId) {
          await wait(); maybeFail('mutate');
          const row = links.find((l) => l.link_id === linkId && l.user === user);
          if (!row) throw notFound();
          row.revoked = true;
        },
      };
    },
  };
}

export type MockPortfolioBackend = ReturnType<typeof createMockPortfolioBackend>;
