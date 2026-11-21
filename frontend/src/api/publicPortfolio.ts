/**
 * 공개 포트폴리오 (T130 화면). 정책: docs/enterprise/T128_PUBLIC_PROFILE_CONSENT_POLICY.md — **PROPOSED, openapi.yaml 에 없음**.
 * 서버(T129)는 `PUBLIC_PORTFOLIO_API=true` 일 때만 경로가 생기고(기본 꺼짐), 저장소는 PostgreSQL(migration 0007)입니다.
 * 비공개가 기본이고, 선택 → 미리보기 → 확인(동의) 뒤에만 공유 링크를 만들 수 있습니다.
 */
import type { HttpClient } from './http';
import type { Experience, Project } from './me';

export const PUBLISHABLE = [
  'display_name', 'headline', 'bio', 'location_text', 'experience.organization', 'experience.title',
  'experience.period', 'experience.description', 'project.title', 'project.summary', 'project.period', 'skills',
  'target_roles',
] as const;
export type PublishableField = (typeof PUBLISHABLE)[number];
export const NEVER_PUBLIC = ['email', 'documents', 'analysis_results', 'job_applications', 'behavior_events',
  'consents_and_account'] as const;

export const FIELD_LABELS: Record<PublishableField, string> = {
  display_name: '이름(또는 별칭)', headline: '한 줄 소개', bio: '자기소개', location_text: '지역',
  'experience.organization': '회사·기관', 'experience.title': '직무·직함', 'experience.period': '기간(연·월)',
  'experience.description': '업무 설명', 'project.title': '프로젝트 이름', 'project.summary': '프로젝트 요약',
  'project.period': '프로젝트 기간', skills: '보유 기술', target_roles: '희망 직무',
};
export const NEVER_LABELS: Record<(typeof NEVER_PUBLIC)[number], string> = {
  email: '이메일·연락처', documents: '이력서 등 업로드 문서', analysis_results: 'AI 분석·적합도 결과',
  job_applications: '지원 기록', behavior_events: '이용 기록', consents_and_account: '계정·동의 정보',
};
export const MAX_ACTIVE_LINKS = 3;
export const TTL_CHOICES = [7, 30, 90] as const;

export type Selection = {
  fields: PublishableField[]; experience_ids: string[]; project_ids: string[]; alias: string | null;
  version: number; consented: boolean;
};
export type ShareLink = { link_id: string; created_at: string; expires_at: string; revoked: boolean; views: number };
export type Settings = { selection: Selection; links: ShareLink[] };
export type CreatedLink = ShareLink & { url: string; notice: string };
export type PublicProfile = {
  display_name?: string; headline?: string; bio?: string; location_text?: string;
  experiences?: { organization?: string; title?: string; period?: { start: string | null; end: string | null }; description?: string }[];
  projects?: { title?: string; summary?: string; period?: { start: string | null; end: string | null } }[];
  skills?: { name: string; proficiency: number | null }[]; target_roles?: string[]; shared_until?: string;
};
/** 선택 화면에 필요한 내 원본 항목(경력·프로젝트 목록) — 서버의 기존 프로필 API 에서 옵니다. */
export type OwnItems = { experiences: { id: string; label: string }[]; projects: { id: string; label: string }[] };

export type SelectionUpdate = { fields: PublishableField[]; experience_ids: string[]; project_ids: string[];
  alias: string | null; version: number };

export interface PortfolioService {
  settings(signal?: AbortSignal): Promise<Settings>;
  ownItems(signal?: AbortSignal): Promise<OwnItems>;
  updateSelection(body: SelectionUpdate): Promise<Selection>;
  preview(signal?: AbortSignal): Promise<PublicProfile>;
  confirm(version: number): Promise<Selection>;
  withdraw(): Promise<void>;
  createLink(ttlDays: number): Promise<CreatedLink>;
  revokeLink(linkId: string): Promise<void>;
}

export interface PublicPortfolioReader {
  view(token: string, signal?: AbortSignal): Promise<PublicProfile>;
}

const ME = '/v1/me/public-profile';

/**
 * 실제 API 어댑터(T129, migration 0007). 계약: backend/app/routers/public_portfolio.py.
 * - 내 경력·프로젝트 목록은 기존 프로필 API(`/v1/me/experiences`, `/v1/me/projects`)에서 옵니다.
 * - 공개 조회는 로그인 토큰 없이 보냅니다(`token: null`) — 받는 사람은 로그인하지 않습니다.
 */
export function createHttpPortfolioService(http: HttpClient): PortfolioService & PublicPortfolioReader {
  return {
    settings: (signal) => http.request<Settings>(ME, { signal }),
    ownItems: async (signal) => {
      const [experiences, projects] = await Promise.all([
        http.request<Experience[]>('/v1/me/experiences', { signal }),
        http.request<Project[]>('/v1/me/projects', { signal }),
      ]);
      return {
        experiences: experiences.map((e) => ({ id: e.experience_id, label: `${e.organization} · ${e.title}` })),
        projects: projects.map((p) => ({ id: p.project_id, label: p.title })),
      };
    },
    updateSelection: (body) => http.request<Selection>(`${ME}/selection`, { method: 'PUT', body }),
    preview: (signal) => http.request<PublicProfile>(`${ME}/preview`, { signal }),
    confirm: (version) => http.request<Selection>(`${ME}/consent`, { method: 'POST', body: { version } }),
    withdraw: () => http.request<void>(`${ME}/consent`, { method: 'DELETE' }),
    createLink: (ttl_days) => http.request<CreatedLink>(`${ME}/links`, { method: 'POST', body: { ttl_days } }),
    revokeLink: (id) => http.request<void>(`${ME}/links/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    view: (token, signal) => http.request<PublicProfile>(`/v1/public/portfolios/${encodeURIComponent(token)}`,
      { signal, token: null }),
  };
}
