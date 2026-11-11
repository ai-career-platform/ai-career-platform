/**
 * T143 내 데이터 반출 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음. T142 서버 규칙을 흉내 냅니다.
 * - 반출 요청·다운로드 링크는 10분 안 재인증이 필요(없으면 403 FORBIDDEN). 비밀번호는 Mock 로그인 비밀번호(MOCK_PASSWORD).
 * - 열린 요청이 있으면 409 CONFLICT. 처리는 `processingMs` 뒤 완료(시험에서는 `process()`로 바로 진행).
 * - 다운로드 링크 1회·10분, 받으면 요청은 expired. 완료 후 24시간이 지나면 expired.
 * - 묶음에는 비밀번호·토큰·IP 해시·저장 키를 넣지 않습니다(T141 never_export_columns).
 * 사용자 ID 는 Mock 로그인과 같이 이메일입니다.
 */
import { ApiError } from '../api/errors';
import type { DataRequest, DownloadLink, PersonalDataService, Reauth } from '../api/personalData';
import { MOCK_PASSWORD } from './handlers';

const MIN = 60_000;
const HOUR = 60 * MIN;
const PATH = '/v1/me/data-requests';

export type MockPersonalDataOptions = { now?: () => Date; latencyMs?: number; processingMs?: number };
type Failure = 'load' | 'mutate' | 'process';
type Row = DataRequest & { user: string; created: number; artifact: string | null; readyAt: number };

export function createMockPersonalDataBackend(options: MockPersonalDataOptions = {}) {
  const now = options.now ?? (() => new Date());
  const rows: Row[] = [];
  const reauths = new Map<string, { user: string; expires: number }>();
  const links = new Map<string, { id: string; expires: number }>();
  const deletions = new Map<string, DataRequest>();
  let seq = 0;
  let failures: Failure[] = [];

  const wait = (signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, options.latencyMs ?? 0);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
  });
  function maybeFail(kind: Failure) {
    if (failures[0] !== kind) return false;
    failures = failures.slice(1);
    if (kind !== 'process') throw new ApiError(0, PATH);
    return true;
  }
  const err = (status: number, code: string, message: string) => new ApiError(status, PATH, undefined, code, message);
  const notFound = () => err(404, 'NOT_FOUND', '요청한 정보를 찾을 수 없습니다.');
  const conflict = () => err(409, 'CONFLICT', '현재 상태에서는 처리할 수 없습니다.');
  const reauthRequired = () => err(403, 'FORBIDDEN', '권한이 없습니다.');
  const token = () => Array.from({ length: 5 }, () => Math.random().toString(36).slice(2, 11)).join('').padEnd(44, 'x');
  const iso = (t: number) => new Date(t).toISOString();
  const view = ({ user: _u, created: _c, artifact: _a, readyAt: _r, ...rest }: Row): DataRequest => structuredClone(rest);
  const set = (row: Row, change: Partial<Row>) => Object.assign(row, change, { updated_at: iso(now().getTime()) });

  function checkReauth(user: string, value: string) {
    const grant = reauths.get(value);
    if (!grant || grant.user !== user || grant.expires <= now().getTime()) throw reauthRequired();
  }
  function bundle(user: string) {
    // 합성 데이터. 금지 항목은 처음부터 넣지 않습니다(서버도 어떤 깊이에서든 제거).
    return JSON.stringify({ format: 'ai-career-export/v1', generated_at: now().toISOString(), data: {
      account: { email: user, display_name: '가상 사용자' },
      career: { experiences: [{ organization: '가상테크', title: '백엔드 개발자' }], skills: [{ name: 'Python', proficiency: 4 }] },
      documents: [{ original_filename: 'resume-sample.pdf', size_bytes: 1024 }],
    } }, null, 2);
  }
  /** 시간이 지난 요청을 진행시킵니다(처리 완료·만료). 조회할 때마다 부릅니다. */
  function tick() {
    const t = now().getTime();
    for (const row of rows) {
      if (row.status === 'received' && t >= row.readyAt) {
        if (maybeFail('process')) {
          set(row, { status: 'failed', reason_code: 'dependency_unavailable', attempts: (row.attempts ?? 0) + 1 });
        } else {
          set(row, { status: 'completed', completed_at: iso(t), expires_at: iso(t + 24 * HOUR), attempts: (row.attempts ?? 0) + 1,
            artifact: bundle(row.user), reason_code: null });
          row.size_bytes = row.artifact!.length;
        }
      }
      if (row.status === 'completed' && row.expires_at && new Date(row.expires_at).getTime() <= t) {
        set(row, { status: 'expired', artifact: null });
      }
    }
  }
  const owned = (user: string, id: string) => {
    const row = rows.find((r) => r.request_id === id && r.user === user);
    if (!row) throw notFound();
    return row;
  };

  return {
    failNext(...kinds: Failure[]) { failures = [...failures, ...kinds]; },
    /** 시험용: 대기 중인 요청을 바로 처리 시점으로 당깁니다. */
    process() { for (const r of rows) if (r.status === 'received') r.readyAt = 0; tick(); },
    /** 시험용: 실패한 요청을 처리 대기로 되돌립니다(서버 Worker 재시도 흉내, 3회 한도). */
    retryFailed() { for (const r of rows) if (r.status === 'failed' && (r.attempts ?? 0) < 3) set(r, { status: 'received', readyAt: 0 }); },
    /** 시험·개발용: T31 탈퇴 요청이 있는 사용자 */
    addDeletion(user: string, status: 'received' | 'cancelled' | 'closed') {
      const t = now().getTime() - 86_400_000;
      deletions.set(user, { request_id: `del-${user}`, request_type: 'erasure', status, created_at: iso(t), updated_at: iso(t), source: 'T31' });
    },
    serviceFor(user: string): PersonalDataService {
      return {
        async list(signal) {
          await wait(signal); maybeFail('load'); tick();
          const items = rows.filter((r) => r.user === user).map(view);
          const deletion = deletions.get(user);
          return [...items, ...(deletion ? [structuredClone(deletion)] : [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
        },
        async reauth(password): Promise<Reauth> {
          await wait(); maybeFail('mutate');
          if (password !== MOCK_PASSWORD) throw err(401, 'INVALID_CREDENTIALS', '이메일 또는 비밀번호가 올바르지 않습니다.');
          const value = token();
          const expires = now().getTime() + 10 * MIN;
          reauths.set(value, { user, expires });
          return { reauth_token: value, expires_at: iso(expires) };
        },
        async createExport(reauthToken) {
          await wait(); maybeFail('mutate'); tick();
          checkReauth(user, reauthToken);
          if (rows.some((r) => r.user === user && ['received', 'in_progress', 'failed', 'completed'].includes(r.status))) throw conflict();
          const t = now().getTime();
          const row: Row = { request_id: `exp-${++seq}`, request_type: 'export', status: 'received', created_at: iso(t + seq),
            updated_at: iso(t), attempts: 0, source: 'T142', user, created: t, artifact: null, readyAt: t + (options.processingMs ?? 3000) };
          rows.push(row);
          return view(row);
        },
        async cancelExport(id) {
          await wait(); maybeFail('mutate'); tick();
          const row = owned(user, id);
          if (row.status !== 'received') throw conflict();
          return view(set(row, { status: 'cancelled' }));
        },
        async downloadLink(id, reauthToken): Promise<DownloadLink> {
          await wait(); maybeFail('mutate'); tick();
          checkReauth(user, reauthToken);
          const row = owned(user, id);
          if (row.status !== 'completed' || !row.artifact) throw conflict();
          for (const [k, v] of links) if (v.id === id) links.delete(k);
          const value = token();
          links.set(value, { id, expires: Math.min(now().getTime() + 10 * MIN, new Date(row.expires_at!).getTime()) });
          return { token: value, expires_at: iso(links.get(value)!.expires), uses: 1, notice: '이 다운로드는 한 번만 받을 수 있습니다.' };
        },
        async download(value) {
          await wait(); maybeFail('mutate'); tick();
          const link = links.get(value);
          links.delete(value);
          const row = link && rows.find((r) => r.request_id === link.id && r.user === user);
          if (!link || !row || link.expires <= now().getTime() || row.status !== 'completed' || !row.artifact) throw notFound();
          const blob = new Blob([row.artifact], { type: 'application/json' });
          set(row, { status: 'expired', artifact: null });
          return blob;
        },
      };
    },
  };
}

export type MockPersonalDataBackend = ReturnType<typeof createMockPersonalDataBackend>;
