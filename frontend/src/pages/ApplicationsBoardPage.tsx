/**
 * UI-N05 개인 지원 현황 보드 (T103, F-012·F-013, 제안 FR-JOB-008).
 * - 사용자가 **직접 기록한** 단계입니다. 채용사·잡코리아의 실제 지원 결과와 자동으로 연결되지 않습니다(화면에 명시).
 * - 단계 변경은 허용된 단계만 고르는 선택 상자(끌어 놓기 없음 — 키보드·스크린리더로도 같은 동작).
 * - 바꾸면 바로 반영하고(낙관적), 저장에 실패하면 원래 단계로 되돌리고 알립니다. 다른 곳에서 먼저 바뀌었으면(409) 최신 내용을 다시 불러옵니다.
 * - 지금은 Mock Adapter 만 연결됩니다(서버 T102 는 기능 플래그 뒤, 기본 꺼짐).
 */
import { useId, useState } from 'react';
import { Link } from 'react-router';
import { ApiError } from '../api/errors';
import {
  MEMO_MAX, STAGES, STAGE_LABELS, TRANSITIONS, type JobApplication, type JobApplicationUpdate, type Stage,
} from '../api/jobApplications';
import { useQuery } from '../api/useQuery';
import { useApplicationService } from '../applications/applicationContext';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { StatePanel } from '../components/StatePanel';
import './ApplicationsBoardPage.css';

const dateText = (value: string | null) => (value ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeZone: 'Asia/Seoul' })
  .format(new Date(`${value}T00:00:00+09:00`)) : null);

function postingBadge(posting: JobApplication['posting']) {
  if (posting.status === 'closed') return <span className="apps-badge apps-badge--closed">마감된 공고</span>;
  if (posting.status === 'unavailable') return <span className="apps-badge apps-badge--gone">공고 정보 없음</span>;
  return null;
}

function failure(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 원래 상태로 되돌렸습니다.';
    if (error.status === 409) return '다른 곳에서 먼저 바뀌었거나 지금은 바꿀 수 없는 단계입니다. 최신 내용을 다시 불러왔습니다.';
    if (error.status === 404) return '이미 삭제된 기록입니다. 목록을 다시 불러왔습니다.';
  }
  return fallback;
}

function Card({ app, busy, onSave, onDelete }: {
  app: JobApplication; busy: boolean;
  onSave: (app: JobApplication, patch: Omit<JobApplicationUpdate, 'version'>, label: string) => void;
  onDelete: (app: JobApplication) => void;
}) {
  const id = useId();
  const [memo, setMemo] = useState(app.memo ?? '');
  const targets = [app.stage, ...TRANSITIONS[app.stage]];
  return (
    <li className="apps-card">
      <div className="apps-card__head">
        <strong>{app.posting.title}</strong>
        {postingBadge(app.posting)}
      </div>
      <p className="apps-muted">{app.posting.company_name}</p>
      <dl className="apps-facts">
        {app.applied_on && <div><dt>지원일(내 기록)</dt><dd>{dateText(app.applied_on)}</dd></div>}
        {app.next_step_on && <div><dt>다음 일정</dt><dd>{dateText(app.next_step_on)}</dd></div>}
      </dl>
      <label htmlFor={`${id}-stage`} className="apps-label">단계</label>
      <select id={`${id}-stage`} value={app.stage} disabled={busy}
        onChange={(e) => onSave(app, { stage: e.target.value as Stage }, `단계를 ‘${STAGE_LABELS[e.target.value as Stage]}’(으)로 바꿨습니다.`)}>
        {targets.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
      </select>
      <details className="apps-memo">
        <summary>메모{app.memo ? ' (있음)' : ''}</summary>
        <label htmlFor={`${id}-memo`} className="apps-label">메모</label>
        <textarea id={`${id}-memo`} value={memo} maxLength={MEMO_MAX} rows={3} aria-describedby={`${id}-memo-hint`}
          onChange={(e) => setMemo(e.target.value)} />
        <p id={`${id}-memo-hint`} className="apps-muted">주민등록번호·연락처·건강 정보 같은 민감한 내용은 적지 마세요. ({memo.length}/{MEMO_MAX})</p>
        <Button variant="outline" disabled={busy || memo === (app.memo ?? '')}
          onClick={() => onSave(app, { memo: memo.trim() ? memo : null }, '메모를 저장했습니다.')}>메모 저장</Button>
      </details>
      <Button variant="outline" className="apps-delete" disabled={busy} onClick={() => onDelete(app)}
        aria-label={`${app.posting.title} 기록 삭제`}>삭제</Button>
    </li>
  );
}

export function ApplicationsBoardPage() {
  const service = useApplicationService();
  const { state } = useAuth();
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const list = useQuery(['me-job-applications', userId], (signal) => service.list(signal));
  const [view, setView] = useState<'board' | 'table'>('board');
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [deleting, setDeleting] = useState<JobApplication | null>(null);

  async function save(app: JobApplication, patch: Omit<JobApplicationUpdate, 'version'>, label: string) {
    setBusy(app.application_id); setMessage(null);
    // 낙관적 반영: 단계만 먼저 바꿔 보여 줌
    if (patch.stage) list.setData((page) => ({ ...page, items: page.items.map((x) => (x.application_id === app.application_id ? { ...x, stage: patch.stage! } : x)) }));
    try {
      const saved = await service.update(app.application_id, { version: app.version, ...patch });
      list.setData((page) => ({ ...page, items: page.items.map((x) => (x.application_id === saved.application_id ? saved : x)) }));
      setMessage({ kind: 'ok', text: `${app.posting.title}: ${label}` });
    } catch (error) {
      list.setData((page) => ({ ...page, items: page.items.map((x) => (x.application_id === app.application_id ? app : x)) }));
      setMessage({ kind: 'error', text: `${app.posting.title}: ${failure(error, '저장하지 못했습니다. 원래 상태로 되돌렸습니다.')}` });
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) list.retry();
    } finally {
      setBusy(null);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    const app = deleting;
    setBusy(app.application_id); setMessage(null);
    try {
      await service.remove(app.application_id);
      list.setData((page) => ({ ...page, items: page.items.filter((x) => x.application_id !== app.application_id) }));
      setMessage({ kind: 'ok', text: `${app.posting.title} 기록을 삭제했습니다.` });
    } catch (error) {
      setMessage({ kind: 'error', text: `${app.posting.title}: ${failure(error, '삭제하지 못했습니다.')}` });
      if (error instanceof ApiError && error.status === 404) list.retry();
    } finally {
      setBusy(null); setDeleting(null);
    }
  }

  const items = list.status === 'ready' ? list.data.items : [];
  return (
    <section className="apps-page" aria-labelledby="apps-title">
      <h1 id="apps-title">지원 현황</h1>
      <div className="apps-notice" role="note">
        <p><strong>내가 기록한 상태입니다.</strong> 기업의 공식 결과가 아니며, 채용사·채용 사이트의 실제 지원 현황과 자동으로 연결되지 않습니다.</p>
        <p>가상 데이터(Mock)입니다. 서버 연동은 아직 없습니다.</p>
      </div>
      {message && (
        <p className={message.kind === 'error' ? 'apps-error' : 'apps-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>
      )}
      {(list.status === 'loading' || list.status === 'idle') && <StatePanel variant="loading" title="지원 기록을 불러오는 중입니다" />}
      {list.status === 'error' && (
        <StatePanel variant="error" title="지원 기록을 불러오지 못했습니다" description="잠시 후 다시 시도해 주세요."
          actionLabel="다시 시도" onAction={list.retry} />
      )}
      {list.status === 'ready' && items.length === 0 && (
        <div className="apps-empty">
          <StatePanel variant="empty" title="아직 기록한 지원이 없습니다" description="관심 있는 공고를 찾아 지원 현황을 기록해 보세요." />
          <Link to="/job-postings">채용공고 탐색하기</Link>
        </div>
      )}
      {list.status === 'ready' && items.length > 0 && (
        <>
          <div className="apps-toolbar" role="group" aria-label="보기 방식">
            <Button variant={view === 'board' ? 'primary' : 'outline'} aria-pressed={view === 'board'} onClick={() => setView('board')}>보드</Button>
            <Button variant={view === 'table' ? 'primary' : 'outline'} aria-pressed={view === 'table'} onClick={() => setView('table')}>표</Button>
            <span className="apps-muted" aria-live="polite">기록 {items.length}건</span>
          </div>
          {view === 'board' ? (
            <div className="apps-board">
              {STAGES.map((stage) => {
                const column = items.filter((x) => x.stage === stage);
                return (
                  <section key={stage} className="apps-column" aria-labelledby={`apps-col-${stage}`}>
                    <h2 id={`apps-col-${stage}`}>{STAGE_LABELS[stage]} <span className="apps-count">{column.length}건</span></h2>
                    {column.length === 0 ? <p className="apps-muted">없음</p> : (
                      <ul className="apps-cards" aria-labelledby={`apps-col-${stage}`}>
                        {column.map((app) => <Card key={`${app.application_id}:${app.version}`} app={app} busy={busy !== null}
                          onSave={save} onDelete={setDeleting} />)}
                      </ul>
                    )}
                  </section>
                );
              })}
            </div>
          ) : (
            <div className="apps-table-wrap">
              <table className="apps-table">
                <caption>지원 기록 표 (내가 기록한 상태)</caption>
                <thead><tr><th scope="col">공고</th><th scope="col">기업</th><th scope="col">단계</th><th scope="col">지원일</th><th scope="col">다음 일정</th><th scope="col">공고 상태</th></tr></thead>
                <tbody>
                  {items.map((app) => (
                    <tr key={app.application_id}>
                      <th scope="row">{app.posting.title}</th>
                      <td>{app.posting.company_name}</td>
                      <td>{STAGE_LABELS[app.stage]}</td>
                      <td>{dateText(app.applied_on) ?? '—'}</td>
                      <td>{dateText(app.next_step_on) ?? '—'}</td>
                      <td>{postingBadge(app.posting) ?? '모집 중'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {deleting && (
        <ConfirmDialog title="지원 기록을 삭제할까요?" confirmLabel="삭제" pending={busy !== null}
          onConfirm={() => void confirmDelete()} onClose={() => setDeleting(null)}>
          <p>‘{deleting.posting.title}’ 기록과 메모가 바로 지워지며 되돌릴 수 없습니다.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
