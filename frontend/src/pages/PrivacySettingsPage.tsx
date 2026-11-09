import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { ApiError } from '../api/client';
import type { ConsentPolicy, PrivacyConsent, DeletionRequest } from '../api/privacy';
import { policyNames } from '../api/privacy';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { TextField } from '../components/TextField';
import { StatePanel } from '../components/StatePanel';
import { env } from '../config/env';
import './PrivacySettingsPage.css';

type Action = { kind: 'consent'; policy: ConsentPolicy; granted: boolean } | { kind: 'delete' | 'cancel' };

function ConfirmDialog({ title, children, pending, onClose }: {
  title: string; children: ReactNode; pending: boolean; onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('button, input')?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  useEffect(() => { if (pending) box.current?.focus(); }, [pending]);
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape' && !pending) { e.preventDefault(); onClose(); }
    if (e.key !== 'Tab') return;
    const controls = box.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)');
    if (!controls?.length) { e.preventDefault(); box.current?.focus(); return; }
    const first = controls?.[0]; const last = controls?.[controls.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
  }
  return <div className="privacy-overlay"><div ref={box} className="privacy-dialog" role="dialog" tabIndex={-1}
    aria-modal="true" aria-labelledby="privacy-confirm-title" onKeyDown={onKeyDown}>
    <h2 id="privacy-confirm-title">{title}</h2>{children}
    <Button variant="outline" onClick={onClose} disabled={pending}>돌아가기</Button>
  </div></div>;
}

export function PrivacySettingsPage() {
  const { request, logout } = useAuth();
  const navigate = useNavigate();
  const [consents, setConsents] = useState<PrivacyConsent[]>([]);
  const [policies, setPolicies] = useState<ConsentPolicy[]>([]);
  const [deletion, setDeletion] = useState<DeletionRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [action, setAction] = useState<Action | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const mock = env.mockEnabled;

  useEffect(() => {
    let active = true;
    const deletionRequest = request<DeletionRequest>('/v1/me/deletion-request').catch(e => {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    });
    Promise.all([request<PrivacyConsent[]>('/v1/me/consents'),
      request<ConsentPolicy[]>('/v1/consent-policies'), deletionRequest])
      .then(([c,p,d]) => { if (active) { setConsents(c); setPolicies(p); setDeletion(d); setLoaded(true); } })
      .catch(() => { if (active) setError('개인정보 설정을 불러오지 못했습니다. 로그인 상태와 API 연결을 확인해 주세요.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [request]);

  function open(next: Action) { if (busy.current) return; setError(''); setNotice(''); setConfirmation(''); setAction(next); }
  function close() { if (!busy.current) { setAction(null); setConfirmation(''); } }
  async function submit() {
    if (busy.current || !action || (action.kind === 'delete' && confirmation !== 'DELETE')) return;
    busy.current = true; setPending(true); setError(''); setNotice('');
    try {
      if (action.kind === 'consent') {
        const result = await request<PrivacyConsent>('/v1/me/consents', { method: 'POST', body: {
          policy_code: action.policy.policy_code, policy_version: action.policy.version, granted: action.granted,
        } });
        setConsents(previous => [result, ...previous.filter(c => c.consent_id !== result.consent_id)]);
        setNotice('동의 상태를 저장했습니다.');
      } else if (action.kind === 'delete') {
        const result = await request<DeletionRequest>('/v1/me/deletion-request', { method: 'POST', body: { confirmation: 'DELETE' } });
        setDeletion(result); setNotice('탈퇴 요청을 접수했습니다.');
        if (!mock) {
          // T31 revokes all sessions. Reuse T21 logout to clear local state too.
          await logout().catch(() => undefined);
          navigate('/login', { replace: true, state: { privacyNotice: '탈퇴 요청이 접수되어 계정이 비활성화됐습니다. 실제 삭제는 진행하지 않았습니다.' } });
        }
      } else if (mock) {
        await request<void>('/v1/me/deletion-request', { method: 'DELETE' });
        setDeletion(null); setNotice('탈퇴 요청이 취소됐습니다.');
      }
      setAction(null); setConfirmation('');
    } catch {
      setError('요청을 처리하지 못했습니다. 입력값은 유지됩니다. 잠시 후 다시 시도해 주세요.');
    } finally { busy.current = false; setPending(false); }
  }

  const current = new Map<string, PrivacyConsent>();
  for (const consent of [...consents].sort((a,b) => b.recorded_at.localeCompare(a.recorded_at))) {
    if (!current.has(consent.policy_code)) current.set(consent.policy_code, consent);
  }
  return <section className="privacy-page" aria-labelledby="privacy-title">
    <div inert={Boolean(action)}><h1 id="privacy-title">개인정보 설정</h1>
    {mock && <p className="privacy-mode" role="status">Mock 모드: 가상 사용자·정책 데이터이며 실제 PostgreSQL 저장이 아닙니다.</p>}
    {loading && <StatePanel variant="loading" title="개인정보 설정을 불러오는 중" />}
    {error && !action && <p className="privacy-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {loaded && <>
      <h2>내 동의 현황</h2>
      {consents.length === 0 && <StatePanel variant="empty" title="동의 이력이 없습니다" description="선택 항목은 아래에서 동의할 수 있습니다." />}
      <div className="privacy-cards">{policies.map(policy => {
        const row = current.get(policy.policy_code); const label = policyNames[policy.policy_code] ?? policy.policy_code;
        return <article className="privacy-card" aria-label={label} key={policy.policy_code}>
          <h3>{label}</h3><p>{policy.is_required ? '필수' : '선택'}</p>
          <p>정책 버전: {row?.policy_version ?? policy.version}</p>
          {row && row.policy_version !== policy.version && <p>현재 정책: {policy.version}</p>}
          <p>{row ? row.granted ? '동의' : '철회' : '미기록'}</p>
          <p>마지막 기록일: {row ? new Date(row.recorded_at).toLocaleString('ko-KR') : '없음'}</p>
          {!policy.is_required && <Button variant="outline" disabled={pending || (!mock && Boolean(deletion))}
            onClick={() => open({ kind: 'consent', policy, granted: !row?.granted })}>{row?.granted ? '철회' : '동의'}</Button>}
        </article>;
      })}</div>
      <section className="privacy-deletion" aria-labelledby="deletion-title">
        <h2 id="deletion-title">회원 탈퇴 요청</h2>
        <p>요청 접수와 실제 데이터 삭제는 다릅니다. 여기서 즉시 물리 삭제하지 않습니다.</p>
        {deletion ? <>
          <p>상태: <strong>접수됨</strong></p><p>요청일: {new Date(deletion.requested_at).toLocaleString('ko-KR')}</p>
          <p>{deletion.scheduled_purge_at ? `삭제 예정일: ${new Date(deletion.scheduled_purge_at).toLocaleString('ko-KR')}` : '삭제 예정일은 아직 정해지지 않았습니다.'}</p>
          {mock ? <Button variant="outline" disabled={pending} onClick={() => open({ kind: 'cancel' })}>요청 취소 (Mock)</Button>
            : <p>현재 실제 탈퇴 취소는 지원하지 않습니다. 계정 복구·재인증 정책 확인이 필요합니다.</p>}
        </> : <><p>진행 중인 탈퇴 요청이 없습니다.</p><Button disabled={pending} onClick={() => open({ kind: 'delete' })}>회원 탈퇴 요청</Button></>}
      </section>
    </>}
    </div>
    {action && <ConfirmDialog title={action.kind === 'consent' ? '선택 동의 변경 확인' : action.kind === 'delete' ? '탈퇴 요청 확인' : '탈퇴 요청 취소 확인'} pending={pending} onClose={close}>
      {action.kind === 'consent' ? <p>{action.granted ? '선택 항목에 동의하시겠습니까?' : '철회하면 관련 기능을 이용하지 못할 수 있습니다. 계속하시겠습니까?'}</p>
        : action.kind === 'delete' ? <><p>요청하면 계정이 비활성화됩니다. {mock && 'Mock에서는 상태·취소 화면 확인을 위해 가상 로그인을 유지합니다.'}</p>
          <TextField label="확인 문구" hint="DELETE를 정확히 입력해 주세요." value={confirmation} disabled={pending} onChange={e => setConfirmation(e.target.value)} /></>
          : <p>가상 탈퇴 요청을 취소하시겠습니까?</p>}
      {error && <p className="privacy-error" role="alert">{error}</p>}
      <Button onClick={() => void submit()} disabled={pending || (action.kind === 'delete' && confirmation !== 'DELETE')}>
        {pending ? '처리 중…' : action.kind === 'consent' ? '변경 확인' : action.kind === 'delete' ? '탈퇴 요청 접수' : '취소 확인'}
      </Button>
    </ConfirmDialog>}
  </section>;
}
