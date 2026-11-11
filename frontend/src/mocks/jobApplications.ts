/**
 * T103 지원 현황 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음. 사용자 ID 별 저장소(본인 격리).
 * T102 서버 규칙을 흉내 냅니다: 이동 표(T101 §4) 밖이면 409, version 이 다르면 409, 남의 기록은 404,
 * 지원 이후 단계에 지원일이 없으면 KST 오늘, 준비 단계로 돌아가면 지원일 지움.
 * 409 는 서버와 같이 `CONFLICT` 하나입니다(T101 D-7 승인 전).
 */
import { ApiError } from '../api/errors';
import {
  APPLICATIONS_PATH, MEMO_MAX, NEEDS_DATE, canMove,
  type JobApplication, type JobApplicationService, type JobApplicationUpdate, type Stage,
} from '../api/jobApplications';

const DAY = 86_400_000;
const kstDate = (d: Date) => new Date(d.getTime() + 9 * 3_600_000).toISOString().slice(0, 10);

type Seed = { title: string; company: string; stage: Stage; status: JobApplication['posting']['status'];
  appliedDaysAgo?: number; nextInDays?: number; memo?: string; expiresInDays?: number | null };
const SEED: Seed[] = [
  { title: '백엔드 개발자 (가상)', company: '가상테크', stage: 'interested', status: 'published', expiresInDays: 12 },
  { title: '데이터 엔지니어 (가상)', company: '예시소프트', stage: 'preparing', status: 'published', memo: '포트폴리오 정리', expiresInDays: 3 },
  { title: '프론트엔드 개발자 (가상)', company: '샘플랩', stage: 'applied', status: 'published', appliedDaysAgo: 4 },
  { title: '서버 개발자 (가상)', company: '데모데이터', stage: 'interviewing', status: 'published', appliedDaysAgo: 10, nextInDays: 5 },
  { title: 'QA 엔지니어 (가상)', company: '테스트모빌리티', stage: 'applied', status: 'closed', appliedDaysAgo: 20, expiresInDays: -2 },
  { title: '모바일 개발자 (가상)', company: '모의헬스', stage: 'rejected', status: 'unavailable', appliedDaysAgo: 40 },
];

export type MockApplicationOptions = { now?: () => Date; latencyMs?: number; seed?: (userId: string) => Seed[] };
type Failure = 'list' | 'update' | 'remove';

export function createMockApplicationBackend(options: MockApplicationOptions = {}) {
  const now = options.now ?? (() => new Date());
  const stores = new Map<string, JobApplication[]>();
  let failures: Failure[] = [];

  function store(userId: string): JobApplication[] {
    let rows = stores.get(userId);
    if (!rows) {
      const base = now().getTime();
      const prefix = String(stores.size + 1).padStart(3, '0');
      rows = (options.seed ? options.seed(userId) : SEED).map((s, i) => {
        const at = new Date(base - (i + 1) * 3_600_000).toISOString();
        return {
          application_id: `00000000-0000-4000-8${prefix}-${String(i + 1).padStart(12, '0')}`,
          stage: s.stage, applied_on: s.appliedDaysAgo === undefined ? null : kstDate(new Date(base - s.appliedDaysAgo * DAY)),
          next_step_on: s.nextInDays === undefined ? null : kstDate(new Date(base + s.nextInDays * DAY)),
          memo: s.memo ?? null, version: 1, created_at: at, updated_at: at, stage_changed_at: at,
          posting: { job_posting_id: s.status === 'unavailable' ? null : `00000000-0000-4000-8${prefix}-${String(i + 101).padStart(12, '0')}`,
            title: s.title, company_name: s.company, status: s.status,
            expires_at: s.status === 'unavailable' || s.expiresInDays === null || s.expiresInDays === undefined
              ? null : new Date(base + s.expiresInDays * DAY).toISOString() },
        };
      });
      stores.set(userId, rows);
    }
    return rows;
  }
  const wait = (signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, options.latencyMs ?? 0);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
  });
  function maybeFail(kind: Failure) {
    if (failures[0] !== kind) return;
    failures = failures.slice(1);
    throw new ApiError(0, APPLICATIONS_PATH);
  }
  const conflict = () => new ApiError(409, APPLICATIONS_PATH, undefined, 'CONFLICT', '현재 상태에서는 처리할 수 없습니다.');
  const notFound = () => new ApiError(404, APPLICATIONS_PATH, undefined, 'NOT_FOUND', '요청한 정보를 찾을 수 없습니다.');

  return {
    failNext(...kinds: Failure[]) { failures = [...failures, ...kinds]; },
    snapshot(userId: string) { return structuredClone(store(userId)); },
    serviceFor(userId: string): JobApplicationService {
      return {
        async list(signal) {
          await wait(signal); maybeFail('list');
          const items = [...store(userId)].sort((a, b) => b.updated_at.localeCompare(a.updated_at)
            || b.application_id.localeCompare(a.application_id));
          return { items: structuredClone(items), next_cursor: null };
        },
        async update(id, body: JobApplicationUpdate) {
          await wait(); maybeFail('update');
          const row = store(userId).find((x) => x.application_id === id);
          if (!row) throw notFound();
          if (row.version !== body.version) throw conflict();
          const target = body.stage ?? row.stage;
          if (!canMove(row.stage, target)) throw conflict();
          if (body.memo && body.memo.length > MEMO_MAX) throw new ApiError(422, APPLICATIONS_PATH, undefined, 'VALIDATION_FAILED');
          let applied = 'applied_on' in body ? body.applied_on ?? null : row.applied_on;
          if (target === 'interested' || target === 'preparing') applied = null;
          else if (NEEDS_DATE.includes(target) && !applied) applied = kstDate(now());
          const at = now().toISOString();
          Object.assign(row, {
            stage: target, applied_on: applied,
            next_step_on: 'next_step_on' in body ? body.next_step_on ?? null : row.next_step_on,
            memo: 'memo' in body ? body.memo ?? null : row.memo,
            version: row.version + 1, updated_at: at, stage_changed_at: target !== row.stage ? at : row.stage_changed_at,
          });
          return structuredClone(row);
        },
        async remove(id) {
          await wait(); maybeFail('remove');
          const rows = store(userId);
          const index = rows.findIndex((x) => x.application_id === id);
          if (index < 0) throw notFound();
          rows.splice(index, 1);
        },
      };
    },
  };
}

export type MockApplicationBackend = ReturnType<typeof createMockApplicationBackend>;
