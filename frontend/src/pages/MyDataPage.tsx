/**
 * 내 데이터 내려받기·요청 이력 (T143). 정책 T141(PROPOSED), 서버 T142(플래그 뒤, migration 0006).
 * 흐름: 내보내기 요청 → (10분 안 비밀번호 재확인) → 처리 대기 → 완료 → 내려받기(1회, 24시간 안) → 만료.
 * - 재인증이 없거나 만료되어 서버가 403을 주면 비밀번호 확인 창을 열고, 확인 뒤 하던 동작을 이어서 합니다.
 * - 목록은 저장 응답으로 바로 고칩니다(다시 불러오면 화면이 잠깐 사라져 포커스를 잃기 때문). Mock 모드면 Mock Adapter, 아니면 실제 API.
 */
import { useId, useState } from 'react';
import { ApiError } from '../api/errors';
import {
  DOWNLOAD_TTL_HOURS, EXCLUDED_LABELS, INCLUDED_LABELS, REASON_LABELS, REAUTH_MINUTES, STATUS_LABELS, TYPE_LABELS,
  type DataRequest,
} from '../api/personalData';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { env } from '../config/env';
import { Button } from '../components/Button';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { StatePanel } from '../components/StatePanel';
import { usePersonalDataService } from '../personal/personalDataContext';
import './MyDataPage.css';

const when = (iso: string) => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Seoul' }).format(new Date(iso));
const OPEN = new Set(['pending_verification', 'received', 'in_progress', 'failed', 'completed']);
type Pending = { kind: 'create' } | { kind: 'download'; id: string };

function problem(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 401) return '비밀번호가 올바르지 않습니다.';
    if (error.status === 409) return '이미 진행 중인 요청이 있거나, 지금 상태에서는 할 수 없는 동작입니다. 목록을 새로 고쳐 확인해 주세요.';
    if (error.status === 404) return '요청을 찾을 수 없거나 다운로드 기간이 지났습니다.';
    if (error.status === 429) return '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.';
  }
  return '처리하지 못했습니다.';
}

/** 브라우저 저장 창을 띄웁니다. 실패하면 false(파일은 이미 1회 사용됐으므로 사용자에게 알립니다). */
function saveFile(blob: Blob): boolean {
  try {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'my-data-export.json';
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return true;
  } catch {
    return false;
  }
}

export function MyDataPage() {
  const service = usePersonalDataService();
  const { state } = useAuth();
  const me = state.status === 'authenticated' ? state.user.userId : null;
  const id = useId();
  const list = useQuery(['my-data-requests', me], (signal) => service.list(signal));
  const [reauth, setReauth] = useState<{ token: string; expires: number } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [password, setPassword] = useState('');
  const [reauthError, setReauthError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [cancelling, setCancelling] = useState<DataRequest | null>(null);

  const items = list.status === 'ready' ? list.data : [];
  const hasOpenExport = items.some((r) => r.request_type === 'export' && OPEN.has(r.status));
  const replace = (row: DataRequest) => list.setData((rows) => rows.map((r) => (r.request_id === row.request_id ? row : r)));

  async function perform(action: Pending, token: string) {
    setBusy(true); setMessage(null);
    try {
      if (action.kind === 'create') {
        const row = await service.createExport(token);
        list.setData((rows) => [row, ...rows]);
        setMessage({ kind: 'ok', text: '내보내기를 요청했습니다. 준비되면 이 화면에서 내려받을 수 있습니다.' });
      } else {
        const link = await service.downloadLink(action.id, token);
        const saved = saveFile(await service.download(link.token));
        list.setData((rows) => rows.map((r) => (r.request_id === action.id ? { ...r, status: 'expired' } : r)));
        setMessage(saved
          ? { kind: 'ok', text: '내려받았습니다. 같은 파일은 다시 받을 수 없으니 안전한 곳에 보관하세요.' }
          : { kind: 'error', text: '파일을 저장하지 못했습니다. 이 파일은 다시 받을 수 없으니 새로 요청해 주세요.' });
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        // 재인증 만료·없음 → 비밀번호를 다시 확인한 뒤 같은 동작을 이어 합니다.
        setReauth(null); setPending(action);
        return;
      }
      setMessage({ kind: 'error', text: problem(error) });
      if (!(error instanceof ApiError && error.status === 0)) list.retry();
    } finally {
      setBusy(false);
    }
  }

  function start(action: Pending) {
    if (reauth && reauth.expires > Date.now()) void perform(action, reauth.token);
    else { setPassword(''); setReauthError(null); setPending(action); }
  }

  async function confirmPassword() {
    if (!pending || !password) return;
    setBusy(true); setReauthError(null);
    try {
      const grant = await service.reauth(password);
      setReauth({ token: grant.reauth_token, expires: new Date(grant.expires_at).getTime() });
      const action = pending;
      setPending(null); setPassword('');
      setBusy(false);
      await perform(action, grant.reauth_token);
    } catch (error) {
      setReauthError(problem(error));
      setBusy(false);
    }
  }

  async function cancel(row: DataRequest) {
    setBusy(true); setMessage(null);
    try {
      replace(await service.cancelExport(row.request_id));
      setMessage({ kind: 'ok', text: '요청을 취소했습니다.' });
    } catch (error) {
      setMessage({ kind: 'error', text: problem(error) });
      list.retry();
    } finally {
      setBusy(false); setCancelling(null);
    }
  }

  return (
    <section className="mydata-page" aria-labelledby={`${id}-title`}>
      <h1 id={`${id}-title`}>내 데이터 내려받기</h1>
      <div className="mydata-notice" role="note">
        <p>이 서비스에 저장된 내 정보를 파일(JSON)로 내려받을 수 있습니다. 요청과 내려받기 전에는 <strong>비밀번호를 다시 확인</strong>합니다({REAUTH_MINUTES}분 동안 유효).</p>
        <p>준비된 파일은 <strong>{DOWNLOAD_TTL_HOURS}시간 안에 한 번만</strong> 내려받을 수 있고, 그 뒤 서버에서 지웁니다.</p>
        {env.mockEnabled && <p>가상 데이터(Mock)입니다. 서버 연동은 아직 없습니다.</p>}
      </div>
      <div className="mydata-columns">
        <div>
          <h2 className="mydata-subtitle">포함되는 정보</h2>
          <ul>{INCLUDED_LABELS.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
        <div>
          <h2 className="mydata-subtitle">포함되지 않는 정보</h2>
          <ul>{EXCLUDED_LABELS.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      </div>

      {message && <p className={message.kind === 'error' ? 'mydata-error' : 'mydata-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}

      <div className="mydata-actions">
        <Button onClick={() => start({ kind: 'create' })} disabled={busy || list.status !== 'ready' || hasOpenExport}
          aria-describedby={hasOpenExport ? `${id}-open` : undefined}>
          내 데이터 내보내기 요청
        </Button>
        <Button variant="outline" onClick={list.retry} disabled={busy}>상태 새로 고침</Button>
        {hasOpenExport && <p id={`${id}-open`} className="mydata-hint">진행 중인 내보내기 요청이 있어 새로 요청할 수 없습니다.</p>}
      </div>

      <h2 id={`${id}-history`}>요청 이력</h2>
      {(list.status === 'loading' || list.status === 'idle') && <StatePanel variant="loading" title="요청 이력을 불러오는 중입니다" />}
      {list.status === 'error' && <StatePanel variant="error" title="요청 이력을 불러오지 못했습니다" actionLabel="다시 시도" onAction={list.retry} />}
      {list.status === 'ready' && items.length === 0 && <StatePanel variant="empty" title="아직 요청한 내역이 없습니다" />}
      {list.status === 'ready' && items.length > 0 && (
        <ul className="mydata-list" aria-labelledby={`${id}-history`}>
          {items.map((row) => (
            <li key={row.request_id} className="mydata-item">
              <div className="mydata-item__head">
                <strong>{TYPE_LABELS[row.request_type]}</strong>
                <span className={`mydata-status mydata-status--${row.status}`}>{STATUS_LABELS[row.status]}</span>
              </div>
              <dl className="mydata-meta">
                <div><dt>요청</dt><dd>{when(row.created_at)}</dd></div>
                {row.completed_at && <div><dt>완료</dt><dd>{when(row.completed_at)}</dd></div>}
                {row.status === 'completed' && row.expires_at && <div><dt>내려받기 기한</dt><dd>{when(row.expires_at)}</dd></div>}
              </dl>
              {row.status === 'failed' && <p className="mydata-reason">{REASON_LABELS[row.reason_code ?? ''] ?? '처리하지 못했습니다.'}</p>}
              {row.source === 'T31' && <p className="mydata-hint">회원 탈퇴 요청은 계정 설정의 개인정보 화면에서 관리합니다.</p>}
              <div className="mydata-item__actions">
                {row.request_type === 'export' && row.status === 'completed' && (
                  <Button onClick={() => start({ kind: 'download', id: row.request_id })} disabled={busy}
                    aria-label={`${when(row.created_at)} 요청 파일 내려받기`}>내려받기</Button>
                )}
                {row.request_type === 'export' && row.status === 'received' && (
                  <Button variant="outline" onClick={() => setCancelling(row)} disabled={busy}
                    aria-label={`${when(row.created_at)} 요청 취소`}>요청 취소</Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {pending && (
        <ConfirmDialog title="비밀번호 다시 확인" confirmLabel="확인" pending={busy} confirmDisabled={!password}
          onConfirm={() => void confirmPassword()} onClose={() => { setPending(null); setPassword(''); }}>
          <form onSubmit={(e) => { e.preventDefault(); void confirmPassword(); }}>
            <p>개인정보 보호를 위해 {pending.kind === 'create' ? '내보내기를 요청하기' : '파일을 내려받기'} 전에 비밀번호를 다시 확인합니다.</p>
            <label htmlFor={`${id}-pw`}>비밀번호</label>
            <input id={`${id}-pw`} type="password" autoComplete="current-password" value={password}
              aria-invalid={!!reauthError} aria-describedby={reauthError ? `${id}-pw-error` : undefined}
              onChange={(e) => setPassword(e.target.value)} />
            {reauthError && <p id={`${id}-pw-error`} className="mydata-error" role="alert">{reauthError}</p>}
          </form>
        </ConfirmDialog>
      )}
      {cancelling && (
        <ConfirmDialog title="내보내기 요청을 취소할까요?" confirmLabel="요청 취소" pending={busy}
          onConfirm={() => void cancel(cancelling)} onClose={() => setCancelling(null)}>
          <p>처리가 시작되기 전에만 취소할 수 있습니다.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
