import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useCrawlerAdminService } from '../../admin/crawlerAdminContext';
import {
  JOB_STATUSES, KEYWORD_MAX, LOCAL_TIME_PATTERN, crawlerAdminErrorMessage, newIdempotencyKey, normalizeKeywordInput,
  reasonText,
  type CommandRecord, type CommandResult, type CrawlerJob, type CrawlerRun, type JobStatus, type KeywordStat, type RunEvent,
} from '../../api/crawlerAdmin';
import { useQuery } from '../../api/useQuery';
import { Button } from '../../components/Button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { DataTable, type TableColumn } from '../../components/DataTable';
import { StatePanel } from '../../components/StatePanel';
import { formatKstDateTime } from './adminAuditFormat';

const JOB_STATUS_TEXT: Record<JobStatus, string> = {
  PENDING: '대기', RUNNING: '진행 중', FETCHED: '수집됨', FAILED: '실패', COMPLETED: '완료', CANCELLED: '취소',
};
const RUN_STATUS_TEXT: Record<CrawlerRun['status'], string> = {
  RUNNING: '진행 중', SUCCEEDED: '성공', PARTIAL: '일부 성공', FAILED: '실패', CANCELLED: '취소',
};
const AUDIT_TEXT = { CREATE: '추가', EDIT: '수정', SET_ENABLED: '활성 변경', SOFT_DELETE: '삭제' } as const;
const time = (iso: string | null | undefined) => (iso ? formatKstDateTime(iso) : '—');
const count = (value: number | null) => (value === null ? '—' : String(value));

type Feedback = { kind: 'ok' | 'error'; text: string } | null;

/** 버튼 동작 하나를 실행하고 결과 문구를 남깁니다. 처리 중 두 번 누르면 무시합니다(포커스 유지를 위해 disabled 대신). */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  async function run(action: () => Promise<string>, after?: () => void) {
    if (busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      setFeedback({ kind: 'ok', text: await action() });
      after?.();
    } catch (error) {
      setFeedback({ kind: 'error', text: crawlerAdminErrorMessage(error).message });
      after?.();
    } finally {
      setBusy(false);
    }
  }
  return { busy, feedback, run, clear: () => setFeedback(null) };
}

function FeedbackLine({ feedback }: { feedback: Feedback }) {
  return (
    <>
      <p className="crawler-status" role="status" aria-live="polite">{feedback?.kind === 'ok' ? feedback.text : ''}</p>
      {feedback?.kind === 'error' && <p className="crawler-error" role="alert">{feedback.text}</p>}
    </>
  );
}

function LoadError({ error, onRetry, title }: { error: unknown; onRetry: () => void; title: string }) {
  const info = crawlerAdminErrorMessage(error);
  return (
    <StatePanel variant={info.forbidden ? 'unauthorized' : 'error'} title={title} description={info.message}
      actionLabel={info.retry ? '다시 시도' : undefined} onAction={info.retry ? onRetry : undefined} />
  );
}

function commandText(result: CommandResult, done: string) {
  return result.replayed ? `이미 처리된 요청입니다(${reasonText(result.reason)}).` : done;
}

function validateKeyword(keyword: string, priority: string): string | null {
  const display = normalizeKeywordInput(keyword);
  if (!display) return '검색어를 입력해 주세요.';
  if (display.length > KEYWORD_MAX) return `검색어는 ${KEYWORD_MAX}자 이하로 입력해 주세요.`;
  const p = Number(priority);
  if (!Number.isInteger(p) || p < 1 || p > 9999) return '우선순위는 1~9999 사이 정수입니다.';
  return null;
}

// ------------------------------------------------------------------ 검색어
export function KeywordsPanel({ onShowJobs }: { onShowJobs: (keywordId: number) => void }) {
  const service = useCrawlerAdminService();
  const stats = useQuery(['crawler-keyword-stats'], (signal) => service.listKeywordStats(signal));
  const action = useAction();
  const [keyword, setKeyword] = useState('');
  const [priority, setPriority] = useState('100');
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState<KeywordStat | null>(null);
  const [deleting, setDeleting] = useState<KeywordStat | null>(null);
  const [auditFor, setAuditFor] = useState<KeywordStat | null>(null);

  function create(event: FormEvent) {
    event.preventDefault();
    const problem = validateKeyword(keyword, priority);
    setFormError(problem);
    if (problem) return;
    void action.run(async () => {
      const created = await service.createKeyword({ keyword: normalizeKeywordInput(keyword), priority: Number(priority) });
      setKeyword('');
      return `검색어 "${created.keyword}"를 추가했습니다.`;
    }, stats.retry);
  }

  const columns: TableColumn<KeywordStat>[] = [
    { key: 'priority', header: '우선순위', render: (k) => <span className="crawler-number">{k.priority}</span> },
    { key: 'keyword', header: '검색어', render: (k) => <span className="crawler-keyword">{k.keyword}</span> },
    { key: 'enabled', header: '상태', render: (k) => (k.enabled ? '활성' : '비활성') },
    { key: 'jobs', header: '작업 수', render: (k) => <span className="crawler-number">{k.job_count}</span> },
    { key: 'found', header: '발견 공고', render: (k) => <span className="crawler-number">{k.discovered_posting_count}</span> },
    {
      key: 'actions', header: '관리', render: (k) => (
        <div className="crawler-actions">
          <Button variant="outline" onClick={() => { action.clear(); setEditing(k); }}
            aria-label={`${k.keyword} 수정`}>수정</Button>
          <Button variant="outline" aria-label={`${k.keyword} ${k.enabled ? '비활성화' : '활성화'}`}
            onClick={() => void action.run(async () => {
              const row = await service.setKeywordEnabled(k.keyword_id, !k.enabled);
              return `"${row.keyword}"를 ${row.enabled ? '활성화' : '비활성화'}했습니다.`;
            }, stats.retry)}>{k.enabled ? '비활성화' : '활성화'}</Button>
          <Button variant="outline" aria-label={`${k.keyword} Fixture 실행`}
            onClick={() => void action.run(async () => {
              const result = await service.runKeyword(k.keyword_id, newIdempotencyKey());
              return commandText(result, `"${k.keyword}" Fixture 작업을 대기열에 만들었습니다(PENDING).`);
            }, stats.retry)}>Fixture 실행</Button>
          <Button variant="outline" aria-label={`${k.keyword} 작업 보기`} onClick={() => onShowJobs(k.keyword_id)}>작업</Button>
          <Button variant="outline" aria-label={`${k.keyword} 변경 이력`} onClick={() => setAuditFor(k)}>이력</Button>
          <Button variant="outline" aria-label={`${k.keyword} 삭제`} onClick={() => setDeleting(k)}>삭제</Button>
        </div>
      ),
    },
  ];

  return (
    <div className="crawler-section">
      <h2>검색어</h2>
      <form className="crawler-form" onSubmit={create} aria-label="검색어 추가" aria-busy={action.busy} noValidate>
        <label>검색어
          <input value={keyword} onChange={(e) => setKeyword(e.target.value)} maxLength={KEYWORD_MAX + 20} required
            aria-invalid={formError ? true : undefined} />
        </label>
        <label>우선순위 (1~9999, 작을수록 먼저)
          <input type="number" inputMode="numeric" min={1} max={9999} value={priority}
            onChange={(e) => setPriority(e.target.value)} required />
        </label>
        <Button type="submit">추가</Button>
      </form>
      {formError && <p className="crawler-error" role="alert">{formError}</p>}
      <FeedbackLine feedback={action.feedback} />

      {editing && (
        <KeywordEditor key={editing.keyword_id} target={editing} busy={action.busy}
          onCancel={() => setEditing(null)}
          onSave={(next) => void action.run(async () => {
            const row = await service.updateKeyword(editing.keyword_id, next);
            setEditing(null);
            return `"${row.keyword}"로 수정했습니다.`;
          }, stats.retry)} />
      )}

      {stats.status === 'error' ? (
        <LoadError error={stats.error} onRetry={stats.retry} title="검색어를 불러오지 못했습니다" />
      ) : stats.status === 'ready' && stats.data.length === 0 ? (
        <StatePanel variant="empty" title="등록된 검색어가 없습니다" description="위 양식으로 검색어를 추가해 주세요." />
      ) : (
        <DataTable caption="검색어 목록 (우선순위 순)" columns={columns} rows={stats.status === 'ready' ? stats.data : []}
          getRowKey={(k) => k.keyword_id} loading={stats.status !== 'ready'} />
      )}
      <p className="crawler-muted">
        발견 공고는 검색어로 찾은 공고 수(누적)입니다. 실행별 신규·중복 수는 "실행 이력" 탭에서 확인합니다.
      </p>

      {auditFor && <KeywordAudit target={auditFor} onClose={() => setAuditFor(null)} />}

      {deleting && (
        <ConfirmDialog title={`"${deleting.keyword}" 검색어 삭제`} confirmLabel="삭제" pending={action.busy}
          onClose={() => setDeleting(null)}
          onConfirm={() => void action.run(async () => {
            await service.deleteKeyword(deleting.keyword_id);
            setDeleting(null);
            return `"${deleting.keyword}"를 삭제했습니다.`;
          }, () => { setDeleting(null); stats.retry(); })}>
          <p>삭제하면 목록에서 사라지고 수집에 쓰지 않습니다. 기존 작업·공고 기록은 남습니다.</p>
          <p>같은 이름으로 다시 추가할 수 없습니다(서버 정책).</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function KeywordEditor({ target, busy, onSave, onCancel }: {
  target: KeywordStat; busy: boolean; onSave: (next: { keyword: string; priority: number }) => void; onCancel: () => void;
}) {
  const [keyword, setKeyword] = useState(target.keyword);
  const [priority, setPriority] = useState(String(target.priority));
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => { first.current?.focus(); }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    const problem = validateKeyword(keyword, priority);
    setError(problem);
    if (!problem) onSave({ keyword: normalizeKeywordInput(keyword), priority: Number(priority) });
  }
  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === 'Escape') { event.preventDefault(); onCancel(); }
  }

  return (
    <form className="crawler-form crawler-editor" onSubmit={submit} onKeyDown={onKeyDown} aria-busy={busy}
      aria-label={`검색어 수정: ${target.keyword}`} noValidate>
      <label>새 검색어
        <input ref={first} value={keyword} onChange={(e) => setKeyword(e.target.value)} required />
      </label>
      <label>우선순위
        <input type="number" inputMode="numeric" min={1} max={9999} value={priority} onChange={(e) => setPriority(e.target.value)} />
      </label>
      <Button type="submit">저장</Button>
      <Button variant="outline" onClick={onCancel}>취소</Button>
      {error && <p className="crawler-error" role="alert">{error}</p>}
    </form>
  );
}

function KeywordAudit({ target, onClose }: { target: KeywordStat; onClose: () => void }) {
  const service = useCrawlerAdminService();
  const audit = useQuery(['crawler-keyword-audit', target.keyword_id], (signal) => service.keywordAudit(target.keyword_id, signal));
  return (
    <section className="crawler-subsection" aria-labelledby="crawler-audit-title">
      <h3 id="crawler-audit-title">"{target.keyword}" 변경 이력</h3>
      {audit.status === 'error' ? (
        <LoadError error={audit.error} onRetry={audit.retry} title="변경 이력을 불러오지 못했습니다" />
      ) : (
        <DataTable caption="검색어 변경 이력 (최신 순)" rows={audit.status === 'ready' ? audit.data : []} loading={audit.status !== 'ready'}
          getRowKey={(a) => a.audit_id} columns={[
            { key: 'at', header: '시각', render: (a) => time(a.occurred_at) },
            { key: 'action', header: '변경', render: (a) => AUDIT_TEXT[a.action] },
            { key: 'actor', header: '작업자', render: (a) => <span className="crawler-mono">{a.actor}</span> },
            { key: 'after', header: '변경 후', render: (a) => `${String(a.after_state.keyword ?? '')} · ${a.after_state.enabled ? '활성' : '비활성'} · ${String(a.after_state.priority ?? '')}` },
          ]} />
      )}
      <Button variant="outline" onClick={onClose}>이력 닫기</Button>
    </section>
  );
}

// ------------------------------------------------------------------ 작업
export function JobsPanel({ keywordId, onClearKeyword }: { keywordId?: number; onClearKeyword: () => void }) {
  const service = useCrawlerAdminService();
  const [status, setStatus] = useState<JobStatus | ''>('');
  const jobs = useQuery(['crawler-jobs', status, keywordId ?? null],
    (signal) => service.listJobs({ status: status || undefined, keyword_id: keywordId }, signal));
  const names = useQuery(['crawler-keyword-stats'], (signal) => service.listKeywordStats(signal));
  const action = useAction();
  const nameOf = (id: number) => (names.status === 'ready' ? names.data.find((k) => k.keyword_id === id)?.keyword : undefined) ?? `#${id}`;

  const columns: TableColumn<CrawlerJob>[] = [
    { key: 'created', header: '생성 시각', render: (j) => time(j.created_at) },
    { key: 'keyword', header: '검색어', render: (j) => nameOf(j.keyword_id) },
    { key: 'status', header: '상태', render: (j) => <span className={`crawler-badge crawler-badge--${j.status.toLowerCase()}`}>{JOB_STATUS_TEXT[j.status]}</span> },
    { key: 'error', header: '오류 코드', render: (j) => <span className="crawler-mono">{j.error_code ?? '—'}</span> },
    { key: 'attempts', header: '시도', render: (j) => count(j.attempt_count) },
    {
      key: 'actions', header: '관리', render: (j) => (
        <div className="crawler-actions">
          {j.status === 'PENDING' && (
            <Button variant="outline" aria-label={`${nameOf(j.keyword_id)} 대기 작업 중단`}
              onClick={() => void action.run(async () => commandText(
                await service.stopJob(j.job_id, newIdempotencyKey()), '대기 작업을 취소했습니다.'), jobs.retry)}>중단</Button>
          )}
          {(j.status === 'FAILED' || j.status === 'CANCELLED') && (
            <Button variant="outline" aria-label={`${nameOf(j.keyword_id)} 작업 재시도`}
              onClick={() => void action.run(async () => commandText(
                await service.retryJob(j.job_id, newIdempotencyKey()), '재시도 작업을 대기열에 만들었습니다(PENDING).'), jobs.retry)}>재시도</Button>
          )}
          {(j.status === 'RUNNING' || j.status === 'FETCHED') && <span className="crawler-muted">Worker 처리 중</span>}
        </div>
      ),
    },
  ];

  return (
    <div className="crawler-section">
      <h2>작업</h2>
      <div className="crawler-form" role="group" aria-label="작업 필터">
        <label>상태
          <select value={status} onChange={(e) => setStatus(e.target.value as JobStatus | '')}>
            <option value="">전체</option>
            {JOB_STATUSES.map((s) => <option key={s} value={s}>{JOB_STATUS_TEXT[s]}</option>)}
          </select>
        </label>
        {keywordId !== undefined && (
          <p className="crawler-chip">검색어: {nameOf(keywordId)} <Button variant="outline" onClick={onClearKeyword}>전체 검색어 보기</Button></p>
        )}
        <Button variant="outline" onClick={jobs.retry}>새로 고침</Button>
      </div>
      <FeedbackLine feedback={action.feedback} />
      {jobs.status === 'error' ? (
        <LoadError error={jobs.error} onRetry={jobs.retry} title="작업을 불러오지 못했습니다" />
      ) : jobs.status === 'ready' && jobs.data.length === 0 ? (
        <StatePanel variant="empty" title="조건에 맞는 작업이 없습니다" description="검색어 탭에서 Fixture 실행으로 대기 작업을 만들 수 있습니다." />
      ) : (
        <DataTable caption="작업 목록 (최신 순)" columns={columns} rows={jobs.status === 'ready' ? jobs.data : []}
          getRowKey={(j) => j.job_id} loading={jobs.status !== 'ready'} />
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 실행 이력
export function RunsPanel() {
  const service = useCrawlerAdminService();
  const runs = useQuery(['crawler-runs'], (signal) => service.listRuns(signal));
  const [selected, setSelected] = useState<CrawlerRun | null>(null);
  const failures = runs.status === 'ready' ? runs.data.filter((r) => r.status === 'FAILED' || r.status === 'PARTIAL').length : 0;

  const columns: TableColumn<CrawlerRun>[] = [
    { key: 'started', header: '시작', render: (r) => time(r.started_at) },
    { key: 'trigger', header: '유형', render: (r) => `${r.trigger === 'retry' ? '재시도' : '예약'} · ${r.attempt}회차 · ${r.mode}` },
    { key: 'status', header: '결과', render: (r) => <span className={`crawler-badge crawler-badge--${r.status.toLowerCase()}`}>{RUN_STATUS_TEXT[r.status]}</span> },
    { key: 'counts', header: '수집/신규/중복/실패', render: (r) => <span className="crawler-number">{`${count(r.fetched_count)} / ${count(r.inserted_count)} / ${count(r.duplicate_count)} / ${count(r.failed_count)}`}</span> },
    { key: 'error', header: '오류 코드', render: (r) => <span className="crawler-mono">{r.error_code ?? '—'}</span> },
    { key: 'events', header: '로그', render: (r) => <Button variant="outline" aria-label={`${time(r.started_at)} 실행 로그 보기`} onClick={() => setSelected(r)}>로그</Button> },
  ];

  return (
    <div className="crawler-section">
      <h2>실행 이력</h2>
      {runs.status === 'ready' && <p className="crawler-muted">최근 {runs.data.length}건 중 실패·일부 성공 {failures}건</p>}
      {runs.status === 'error' ? (
        <LoadError error={runs.error} onRetry={runs.retry} title="실행 이력을 불러오지 못했습니다" />
      ) : runs.status === 'ready' && runs.data.length === 0 ? (
        <StatePanel variant="empty" title="실행 이력이 없습니다" />
      ) : (
        <DataTable caption="실행 이력 (최신 순)" columns={columns} rows={runs.status === 'ready' ? runs.data : []}
          getRowKey={(r) => r.run_id} loading={runs.status !== 'ready'} />
      )}
      {selected && <RunEvents run={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function RunEvents({ run, onClose }: { run: CrawlerRun; onClose: () => void }) {
  const service = useCrawlerAdminService();
  const events = useQuery(['crawler-run-events', run.run_id], (signal) => service.listRunEvents(run.run_id, signal));
  return (
    <section className="crawler-subsection" aria-labelledby="crawler-events-title">
      <h3 id="crawler-events-title">{time(run.started_at)} 실행 로그</h3>
      {events.status === 'error' ? (
        <LoadError error={events.error} onRetry={events.retry} title="실행 로그를 불러오지 못했습니다" />
      ) : (
        <DataTable<RunEvent> caption="실행 로그 (최신 순)" rows={events.status === 'ready' ? events.data : []} loading={events.status !== 'ready'}
          getRowKey={(e) => e.event_id} columns={[
            { key: 'at', header: '시각', render: (e) => time(e.occurred_at) },
            { key: 'level', header: '수준', render: (e) => e.level },
            { key: 'type', header: '종류', render: (e) => <span className="crawler-mono">{e.event_type}</span> },
            { key: 'message', header: '내용', render: (e) => e.safe_message },
          ]} />
      )}
      <Button variant="outline" onClick={onClose}>로그 닫기</Button>
    </section>
  );
}

// ------------------------------------------------------------------ 스케줄 설정
export function SettingsPanel() {
  const service = useCrawlerAdminService();
  const settings = useQuery(['crawler-settings'], (signal) => service.getSettings(signal));
  const action = useAction();
  const [draft, setDraft] = useState<Record<string, string>>({});

  if (settings.status === 'error') return <LoadError error={settings.error} onRetry={settings.retry} title="설정을 불러오지 못했습니다" />;
  if (settings.status !== 'ready') return <StatePanel variant="loading" title="설정 불러오는 중" />;
  const data = settings.data;

  return (
    <div className="crawler-section">
      <h2>스케줄 설정</h2>
      {!data.writeApi && (
        <p className="crawler-notice-inline" role="note">서버 쓰기 API(CRAWLER_ADMIN_WRITE_API)가 꺼져 있어 읽기 전용으로 표시합니다.</p>
      )}
      <dl className="crawler-facts">
        <div><dt>실제 사이트 수집</dt><dd>HOLD (승인 전)</dd></div>
        <div><dt>야간 시간창</dt><dd>{data.night_window ? `${data.night_window.start}~${data.night_window.end} KST (변경 불가)` : '확인 불가'}</dd></div>
      </dl>
      <FeedbackLine feedback={action.feedback} />
      {data.schedules.length === 0 ? (
        <StatePanel variant="empty" title="등록된 스케줄이 없습니다" />
      ) : data.schedules.map((s) => {
        const current = s.local_time.slice(0, 5);
        const value = draft[s.schedule_id] ?? current;
        const invalid = !LOCAL_TIME_PATTERN.test(value);
        return (
          <form key={s.schedule_id} className="crawler-form crawler-schedule" aria-label={`${s.schedule_id} 스케줄`}
            aria-busy={action.busy} noValidate onSubmit={(event) => {
              event.preventDefault();
              if (invalid || !data.writeApi) return;
              void action.run(async () => {
                const result = await service.updateScheduleTime(s.schedule_id, value, newIdempotencyKey());
                return commandText(result, result.reason === 'NO_CHANGE' ? '바뀐 값이 없습니다.' : `실행 시각을 ${value} KST로 바꿨습니다. 스케줄은 계속 꺼져 있습니다.`);
              }, settings.retry);
            }}>
            <p className="crawler-schedule-head"><span className="crawler-mono">{s.schedule_id}</span> · {s.mode} · 다음 예정 {time(s.next_run_at)}</p>
            <label className="crawler-check">
              <input type="checkbox" checked={s.enabled} disabled aria-describedby={`enable-note-${s.schedule_id}`} />
              스케줄 활성
            </label>
            <span id={`enable-note-${s.schedule_id}`} className="crawler-muted">활성화는 별도 승인 후 운영 절차로만 합니다.</span>
            <label>실행 시각 (KST)
              <input type="time" value={value} step={60} readOnly={!data.writeApi} aria-invalid={invalid || undefined}
                onChange={(e) => setDraft((d) => ({ ...d, [s.schedule_id]: e.target.value }))} />
            </label>
            {data.writeApi && <Button type="submit">시각 저장</Button>}
            {invalid && <p className="crawler-error" role="alert">시각은 HH:MM 형식입니다.</p>}
          </form>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ 명령 기록
export function CommandsPanel() {
  const service = useCrawlerAdminService();
  const commands = useQuery(['crawler-commands'], (signal) => service.listCommands(signal));
  const columns: TableColumn<CommandRecord>[] = [
    { key: 'at', header: '시각', render: (c) => time(c.created_at) },
    { key: 'type', header: '명령', render: (c) => c.command_type },
    { key: 'target', header: '대상', render: (c) => <span className="crawler-mono">{c.target}</span> },
    { key: 'outcome', header: '결과', render: (c) => <span className={`crawler-badge crawler-badge--${c.outcome.toLowerCase()}`}>{c.outcome === 'ACCEPTED' ? '수락' : '거부'}</span> },
    { key: 'reason', header: '사유', render: (c) => reasonText(c.reason) },
    { key: 'actor', header: '작업자', render: (c) => <span className="crawler-mono">{c.actor}</span> },
  ];
  return (
    <div className="crawler-section">
      <h2>명령 기록</h2>
      <p className="crawler-muted">수락·거부된 관리자 명령이 모두 남습니다(수정·삭제 불가 원장).</p>
      {commands.status === 'error' ? (
        <LoadError error={commands.error} onRetry={commands.retry} title="명령 기록을 불러오지 못했습니다" />
      ) : commands.status === 'ready' && commands.data.length === 0 ? (
        <StatePanel variant="empty" title="아직 명령 기록이 없습니다" />
      ) : (
        <DataTable caption="명령 기록 (최신 순)" columns={columns} rows={commands.status === 'ready' ? commands.data : []}
          getRowKey={(c) => c.command_id} loading={commands.status !== 'ready'} />
      )}
      <Button variant="outline" onClick={commands.retry}>새로 고침</Button>
    </div>
  );
}
