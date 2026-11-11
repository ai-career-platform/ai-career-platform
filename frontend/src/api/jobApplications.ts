/**
 * 개인 지원 현황 (T103). 계약: docs/applications/T101_APPLICATION_TRACKING_CONTRACT.md — **PROPOSED, docs/api/openapi.yaml 에 없음**.
 * 서버(T102)는 `JOB_APPLICATIONS_API=true` 일 때만 경로가 생깁니다(기본 꺼짐). 그래서 화면도 Mock 전용 플래그 뒤에 둡니다.
 * 상태는 **사용자가 직접 기록한 것**이며 채용사 공식 결과가 아닙니다.
 */
import type { HttpClient } from './http';

export const STAGES = ['interested', 'preparing', 'applied', 'interviewing', 'offered', 'rejected', 'withdrawn'] as const;
export type Stage = (typeof STAGES)[number];

export const STAGE_LABELS: Record<Stage, string> = {
  interested: '관심', preparing: '지원 준비', applied: '지원 완료', interviewing: '면접 진행',
  offered: '합격·제안(내 기록)', rejected: '불합격(내 기록)', withdrawn: '지원 취소',
};

/** T101 §4 이동 표(같은 단계 유지는 항상 허용). 화면은 허용된 단계만 고를 수 있게 보여 줍니다. */
export const TRANSITIONS: Record<Stage, readonly Stage[]> = {
  interested: ['preparing', 'applied', 'withdrawn'],
  preparing: ['interested', 'applied', 'withdrawn'],
  applied: ['preparing', 'interviewing', 'offered', 'rejected', 'withdrawn'],
  interviewing: ['applied', 'offered', 'rejected', 'withdrawn'],
  offered: ['interviewing', 'withdrawn'],
  rejected: ['interviewing'],
  withdrawn: ['interested'],
};
export const canMove = (from: Stage, to: Stage) => from === to || TRANSITIONS[from].includes(to);
export const NEEDS_DATE: readonly Stage[] = ['applied', 'interviewing', 'offered', 'rejected'];
export const MEMO_MAX = 2000;

export type JobApplication = {
  application_id: string;
  stage: Stage;
  applied_on: string | null;
  next_step_on: string | null;
  memo: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  stage_changed_at: string;
  posting: { job_posting_id: string | null; title: string; company_name: string;
    status: 'published' | 'closed' | 'unavailable'; expires_at: string | null };
};
export type JobApplicationPage = { items: JobApplication[]; next_cursor: string | null };
export type JobApplicationUpdate = { version: number; stage?: Stage; applied_on?: string | null;
  next_step_on?: string | null; memo?: string | null };

export interface JobApplicationService {
  list(signal?: AbortSignal): Promise<JobApplicationPage>;
  update(id: string, body: JobApplicationUpdate): Promise<JobApplication>;
  remove(id: string): Promise<void>;
}

export const APPLICATIONS_PATH = '/v1/me/job-applications';

/** 실제 API 어댑터(준비만, 연결하지 않음). 한 번에 최대 100건(서버 상한). */
export function createHttpJobApplicationService(http: HttpClient): JobApplicationService {
  return {
    list: (signal) => http.request<JobApplicationPage>(APPLICATIONS_PATH, { query: { limit: 100 }, signal }),
    update: (id, body) => http.request<JobApplication>(`${APPLICATIONS_PATH}/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
    remove: (id) => http.request<void>(`${APPLICATIONS_PATH}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  };
}
