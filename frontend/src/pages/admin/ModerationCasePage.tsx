import { useId, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useModerationService } from '../../admin/moderationContext';
import {
  CLOSE_REASON_LABELS, EVENT_LABELS, FLAG_LABELS, NOTE_MAX_LENGTH, PRIORITY_LABELS, REASON_CODES, REASON_LABELS,
  TARGET_TYPE_LABELS, TRIGGER_LABELS, availableActions, moderationErrorMessage, rejectInputError,
  type ModerationCaseDetail, type ReasonCode,
} from '../../api/moderation';
import { useQuery } from '../../api/useQuery';
import { useAuth } from '../../auth/useAuth';
import { Button } from '../../components/Button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { StatePanel } from '../../components/StatePanel';
import { assigneeLabel, formatDateTime } from './moderationFormat';
import { DueDate, ModerationNotice, StatusBadge } from './moderationUi';
import './Moderation.css';

type Dialog = null | 'approve' | 'reject';
type Failure = { message: string; reload: boolean };

/** UI-027 검수 상세·조치 (T82, Mock 전용). 버튼 활성화는 UX이며 권한 판단은 서버(T81)·Mock Adapter가 합니다. */
export function ModerationCasePage() {
  const { caseId = '' } = useParams();
  const service = useModerationService();
  const { state } = useAuth();
  const viewerId = state.status === 'authenticated' ? state.user.userId : undefined;
  const detail = useQuery(['moderation-case', caseId], (signal) => service.get(caseId, signal));

  const [dialog, setDialog] = useState<Dialog>(null);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [touched, setTouched] = useState(false);
  const busy = useRef(false);
  const reasonId = useId();
  const noteId = useId();
  const formErrorId = useId();

  if (detail.status === 'idle' || detail.status === 'loading') return <StatePanel variant="loading" title="검수 건을 불러오는 중" />;
  if (detail.status === 'error') {
    const { message } = moderationErrorMessage(detail.error);
    return (
      <section className="moderation-page">
        <StatePanel variant="error" title="검수 건을 불러오지 못했습니다" description={message} actionLabel="다시 시도"
          onAction={detail.retry} />
        <Link to="/admin/moderation">검수 목록으로</Link>
      </section>
    );
  }

  const item = detail.data;
  const actions = availableActions(item, viewerId);
  const rejectError = rejectInputError(reason, note);

  /** 같은 조치가 두 번 나가지 않도록 렌더 전에도 잠급니다(연속 클릭 방지). */
  async function run(label: string, action: () => Promise<ModerationCaseDetail>) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setFailure(null);
    setResult(null);
    try {
      const updated = await action();
      detail.setData(() => updated);
      setResult(label);
      setDialog(null);
    } catch (error) {
      setFailure(moderationErrorMessage(error));
      setDialog(null);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  function openReject() {
    setReason('');
    setNote('');
    setTouched(false);
    setDialog('reject');
  }

  function submitReject() {
    setTouched(true);
    if (rejectError) return;
    void run('반려했습니다.', () => service.decide(item.case_id, {
      version: item.version, decision: 'REJECT', reason_code: reason as ReasonCode, note: note.trim() || undefined,
    }));
  }

  function reload() {
    setFailure(null);
    setResult(null);
    detail.retry();
  }

  return (
    <section className="moderation-page" aria-labelledby="moderation-case-title">
      <Link to="/admin/moderation">← 검수 목록</Link>
      <h1 id="moderation-case-title">검수 건 {item.case_id}</h1>
      <ModerationNotice />

      <dl className="moderation-facts">
        <dt>검수 대상</dt><dd>{TARGET_TYPE_LABELS[item.target_type]} · {item.target_summary}</dd>
        <dt>대상 ID</dt><dd><code>{item.target_id}</code></dd>
        <dt>검수 요청 사유</dt><dd>{TRIGGER_LABELS[item.trigger]}{item.report_count ? ` (신고 ${item.report_count}건)` : ''}</dd>
        <dt>상태</dt><dd><StatusBadge status={item.status} />{item.appeal_count === 1 ? ' · 이의제기 재검토 단계' : ''}</dd>
        <dt>우선순위</dt><dd>{PRIORITY_LABELS[item.priority]}</dd>
        <dt>처리 기한</dt><dd><DueDate dueAt={item.due_at} status={item.status} /></dd>
        <dt>담당자</dt><dd>{assigneeLabel(item.assignee_id, viewerId)}</dd>
        {item.reason_code && <><dt>반려 사유</dt><dd>{REASON_LABELS[item.reason_code]} ({item.reason_code})</dd></>}
        {item.decided_at && <><dt>결정</dt><dd>{formatDateTime(item.decided_at)} · {item.decided_by ?? '—'}</dd></>}
        {item.close_reason && <><dt>종료 사유</dt><dd>{CLOSE_REASON_LABELS[item.close_reason]}</dd></>}
      </dl>

      <section aria-labelledby="moderation-flags-title">
        <h2 id="moderation-flags-title">자동 표시</h2>
        {item.flags.length === 0
          ? <p>자동 표시 없음</p>
          : <ul>{item.flags.map((flag) => <li key={flag}>{FLAG_LABELS[flag] ?? flag}</li>)}</ul>}
        <p className="moderation-hint">자동 표시는 참고용이며 결정은 담당 관리자가 합니다.</p>
      </section>

      <section aria-labelledby="moderation-actions-title" className="moderation-actions">
        <h2 id="moderation-actions-title">조치</h2>
        {result && <p role="status" className="moderation-result">{result}</p>}
        {failure && (
          <div role="alert" className="moderation-error">
            <p>{failure.message}</p>
            {failure.reload && <Button variant="outline" onClick={reload}>최신 내용 다시 불러오기</Button>}
          </div>
        )}
        <div className="moderation-buttons">
          <ActionButton label="담당 시작" allowed={actions.assign} pending={pending}
            onClick={() => void run('담당을 시작했습니다.', () => service.assign(item.case_id, { version: item.version }))} />
          <ActionButton label="승인" allowed={actions.decide} pending={pending} onClick={() => setDialog('approve')} />
          <ActionButton label="반려" allowed={actions.decide} pending={pending} variant="outline" onClick={openReject} />
        </div>
        <p className="moderation-hint">
          게시 중단 표시·임시 비공개·이의제기 처리 방식은 T80 정책 승인 전이라 이 화면에서 제공하지 않습니다.
        </p>
      </section>

      <section aria-labelledby="moderation-history-title">
        <h2 id="moderation-history-title">처리 이력</h2>
        <ol className="moderation-history">
          {item.events.map((e) => (
            <li key={e.event_id}>
              <time dateTime={e.occurred_at}>{formatDateTime(e.occurred_at)}</time>{' '}
              <strong>{EVENT_LABELS[e.event]}</strong>{' '}
              {e.from_status ? `${e.from_status} → ` : ''}{e.to_status}
              {' · '}{e.actor_id ?? '시스템'}
              {e.reason_code ? ` · 사유 ${e.reason_code}` : ''}
            </li>
          ))}
        </ol>
      </section>

      {dialog === 'approve' && (
        <ConfirmDialog title="이 검수 건을 승인할까요?" confirmLabel="승인" pending={pending}
          onClose={() => setDialog(null)}
          onConfirm={() => void run('승인했습니다.', () => service.decide(item.case_id, { version: item.version, decision: 'APPROVE' }))}>
          <p>{item.target_summary}</p>
        </ConfirmDialog>
      )}
      {dialog === 'reject' && (
        <ConfirmDialog title="이 검수 건을 반려할까요?" confirmLabel="반려" pending={pending}
          onClose={() => setDialog(null)} onConfirm={submitReject}>
          <div className="moderation-form">
            <label htmlFor={reasonId}>반려 사유 (필수)</label>
            <select id={reasonId} value={reason} onChange={(event) => setReason(event.target.value)} required
              aria-invalid={touched && !!rejectError && !reason} aria-describedby={touched && rejectError ? formErrorId : undefined}>
              <option value="">사유 선택</option>
              {REASON_CODES.map((code) => <option key={code} value={code}>{REASON_LABELS[code]}</option>)}
            </select>
            <label htmlFor={noteId}>{reason === 'OTHER' ? '설명 (필수)' : '설명 (선택)'}</label>
            <textarea id={noteId} value={note} maxLength={NOTE_MAX_LENGTH + 1} rows={3}
              onChange={(event) => setNote(event.target.value)} required={reason === 'OTHER'}
              aria-invalid={touched && reason === 'OTHER' && !note.trim()}
              aria-describedby={touched && rejectError ? formErrorId : undefined} />
            <p className="moderation-hint">설명은 관리자만 봅니다. 개인정보를 적지 마세요. ({note.length}/{NOTE_MAX_LENGTH})</p>
            {touched && rejectError && <p id={formErrorId} role="alert" className="moderation-error">{rejectError}</p>}
          </div>
        </ConfirmDialog>
      )}
    </section>
  );
}

function ActionButton({ label, allowed, pending, onClick, variant }: {
  label: string; allowed: ReturnType<typeof availableActions>['assign']; pending: boolean; onClick: () => void;
  variant?: 'primary' | 'outline';
}) {
  const hintId = useId();
  return (
    <span className="moderation-action">
      <Button variant={variant} onClick={onClick} disabled={pending || !allowed.allowed}
        aria-describedby={allowed.allowed ? undefined : hintId}>{label}</Button>
      {!allowed.allowed && <span id={hintId} className="moderation-hint">{allowed.reason}</span>}
    </span>
  );
}
