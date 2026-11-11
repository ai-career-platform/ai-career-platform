/**
 * 기업 콘솔 — 조직 구성·멤버 초대 (T124, UI 제안 UI-N06). 계약: T121·T122(PROPOSED), 서버 T123(플래그 뒤).
 * - 기업 관리자: 멤버 역할 변경·제외, 초대·재전송·취소. 기업 담당자: 목록 보기, 스스로 나가기.
 * - 검증 전 조직은 초대를 막고 이유를 보여 줍니다. 403(역할 부족)·404(소속 아님)·409(마지막 관리자 등)를 각각 안내합니다.
 * - 지금은 Mock Adapter 만 연결됩니다. 초대 메일은 Mock 메일함에만 쌓입니다.
 */
import { useId, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import {
  INVITATION_LABELS, MAX_RESENDS, ORG_STATUS_LABELS, ROLE_LABELS, type Invitation, type Member, type MemberRole,
} from '../api/companyAccounts';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { useCompanyService, useMockCompanyBackend } from '../company/companyContext';
import { explain } from '../company/companyErrors';
import { Button } from '../components/Button';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { StatePanel } from '../components/StatePanel';
import './CompanyConsolePage.css';

const when = (iso: string) => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Seoul' })
  .format(new Date(iso));

function RegisterForm({ onDone }: { onDone: (id: string) => void }) {
  const service = useCompanyService();
  const id = useId();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null);
    try { onDone((await service.register(name)).organization_id); setName(''); } catch (e) { setError(explain(e, 'register')); } finally { setBusy(false); }
  }
  return (
    <form className="company-form" onSubmit={(e) => void submit(e)} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>기업 등록 신청</h2>
      <p className="company-muted">신청하면 운영자가 회사가 실재하는지 확인합니다. 확인 전에는 멤버 초대·공고 검수 요청을 할 수 없습니다.</p>
      <label htmlFor={`${id}-name`}>회사 이름</label>
      <input id={`${id}-name`} value={name} maxLength={200} required onChange={(e) => setName(e.target.value)} />
      {error && <p className="company-error" role="alert">{error}</p>}
      <Button type="submit" disabled={busy || !name.trim()}>등록 신청</Button>
    </form>
  );
}

function Members({ orgId, myRole, me, onLeft }: { orgId: string; myRole: MemberRole; me: string; onLeft: () => void }) {
  const service = useCompanyService();
  const list = useQuery(['company-members', orgId], (signal) => service.members(orgId, signal));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);

  async function change(member: Member, role: MemberRole) {
    setBusy(true); setMessage(null);
    try {
      const saved = await service.changeRole(orgId, member.user_id, role, member.version);
      list.setData((rows) => rows.map((m) => (m.user_id === saved.user_id ? saved : m)));
      setMessage({ kind: 'ok', text: `${member.display_name}: ${ROLE_LABELS[role]}(으)로 바꿨습니다.` });
    } catch (error) {
      setMessage({ kind: 'error', text: `${member.display_name}: ${explain(error, 'role')}` });
      list.retry();
    } finally { setBusy(false); }
  }
  async function remove() {
    if (!removing) return;
    const target = removing;
    setBusy(true); setMessage(null);
    try {
      await service.removeMember(orgId, target.user_id);
      if (target.user_id === me) { onLeft(); return; }
      list.setData((rows) => rows.filter((m) => m.user_id !== target.user_id));
      setMessage({ kind: 'ok', text: `${target.display_name}님을 조직에서 제외했습니다. 권한은 바로 사라집니다.` });
    } catch (error) {
      setMessage({ kind: 'error', text: explain(error, 'remove') });
    } finally { setBusy(false); setRemoving(null); }
  }

  return (
    <section className="company-section" aria-labelledby="company-members-title">
      <h2 id="company-members-title">멤버</h2>
      {message && <p className={message.kind === 'error' ? 'company-error' : 'company-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}
      {list.status === 'error' && <StatePanel variant="error" title="멤버를 불러오지 못했습니다" actionLabel="다시 시도" onAction={list.retry} />}
      {list.status === 'ready' && (
        <div className="company-table-wrap">
          <table className="company-table">
            <caption>조직 멤버 {list.data.length}명 (이메일은 일부만 표시)</caption>
            <thead><tr><th scope="col">이름</th><th scope="col">이메일</th><th scope="col">역할</th><th scope="col">합류</th><th scope="col">작업</th></tr></thead>
            <tbody>
              {list.data.map((m) => (
                <tr key={`${m.user_id}:${m.version}`}>
                  <th scope="row">{m.display_name}{m.user_id === me && ' (나)'}</th>
                  <td>{m.email_masked}</td>
                  <td>
                    {myRole === 'owner' ? (
                      <select aria-label={`${m.display_name} 역할`} value={m.role} disabled={busy}
                        onChange={(e) => void change(m, e.target.value as MemberRole)}>
                        <option value="owner">{ROLE_LABELS.owner}</option>
                        <option value="member">{ROLE_LABELS.member}</option>
                      </select>
                    ) : ROLE_LABELS[m.role]}
                  </td>
                  <td>{when(m.joined_at)}</td>
                  <td>
                    {(myRole === 'owner' || m.user_id === me) && (
                      <Button variant="outline" disabled={busy} onClick={() => setRemoving(m)}
                        aria-label={m.user_id === me ? '이 조직에서 나가기' : `${m.display_name} 제외`}>
                        {m.user_id === me ? '나가기' : '제외'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {removing && (
        <ConfirmDialog title={removing.user_id === me ? '조직에서 나갈까요?' : '멤버를 제외할까요?'}
          confirmLabel={removing.user_id === me ? '나가기' : '제외'} pending={busy}
          onConfirm={() => void remove()} onClose={() => setRemoving(null)}>
          <p>{removing.user_id === me ? '나가면 이 조직의 콘솔과 공고에 바로 접근할 수 없습니다.'
            : `${removing.display_name}님은 이 조직의 콘솔과 공고에 바로 접근할 수 없게 됩니다.`}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}

function Invitations({ orgId, active }: { orgId: string; active: boolean }) {
  const service = useCompanyService();
  const mock = useMockCompanyBackend();
  const id = useId();
  const list = useQuery(['company-invitations', orgId], (signal) => service.invitations(orgId, signal));
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<MemberRole>('member');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [mockLink, setMockLink] = useState<string | null>(null);
  // 남은 시간 계산 기준(렌더 중 Date.now 호출 금지 — 목록을 새로 받을 때 갱신)
  const [now, setNow] = useState(() => Date.now());

  async function run(action: () => Promise<unknown>, ok: string, context: 'invite' | 'resend' | 'revoke') {
    setBusy(true); setMessage(null);
    try {
      await action();
      setMessage({ kind: 'ok', text: ok });
      setMockLink(mock?.lastInviteLink() ?? null);
      list.retry();
      return true;
    } catch (error) {
      setMessage({ kind: 'error', text: explain(error, context) });
      list.retry();
      return false;
    } finally { setBusy(false); setNow(Date.now()); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await run(() => service.invite(orgId, email, role), `${email} 주소로 초대를 보냈습니다. 72시간 뒤 만료됩니다.`, 'invite')) setEmail('');
  }
  const remaining = (inv: Invitation) => Math.round((new Date(inv.expires_at).getTime() - now) / 3_600_000);

  return (
    <section className="company-section" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>초대</h2>
      {!active && <p className="company-notice" role="note">운영 확인이 끝나야 멤버를 초대할 수 있습니다.</p>}
      <form className="company-form company-form--inline" onSubmit={(e) => void submit(e)}>
        <label htmlFor={`${id}-email`}>초대할 이메일</label>
        <input id={`${id}-email`} type="email" value={email} required disabled={!active} maxLength={254}
          onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor={`${id}-role`}>역할</label>
        <select id={`${id}-role`} value={role} disabled={!active} onChange={(e) => setRole(e.target.value as MemberRole)}>
          <option value="member">{ROLE_LABELS.member}</option>
          <option value="owner">{ROLE_LABELS.owner}</option>
        </select>
        <Button type="submit" disabled={!active || busy || !email.trim()}>초대 보내기</Button>
      </form>
      {message && <p className={message.kind === 'error' ? 'company-error' : 'company-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}
      {mock && mockLink && (
        <p className="company-muted">가상 메일함(Mock 전용): <Link to={mockLink}>초대 링크 열기</Link></p>
      )}
      {list.status === 'error' && <StatePanel variant="error" title="초대 목록을 불러오지 못했습니다" actionLabel="다시 시도" onAction={list.retry} />}
      {list.status === 'ready' && list.data.length === 0 && <p className="company-muted">보낸 초대가 없습니다.</p>}
      {list.status === 'ready' && list.data.length > 0 && (
        <ul className="company-invites">
          {list.data.map((inv) => (
            <li key={`${inv.invitation_id}:${inv.resend_count}:${inv.status}`} className="company-invite">
              <span><strong>{inv.email_masked}</strong> · {ROLE_LABELS[inv.role]}</span>
              <span className={`company-badge company-badge--${inv.status}`}>{INVITATION_LABELS[inv.status]}</span>
              <span className="company-muted">
                {inv.status === 'pending' ? `${remaining(inv)}시간 뒤 만료` : `만료 시각 ${when(inv.expires_at)}`}
                {` · 재전송 ${inv.resend_count}/${MAX_RESENDS}`}
              </span>
              {(inv.status === 'pending' || inv.status === 'expired') && active && (
                <span className="company-actions">
                  {inv.status === 'pending' && (
                    <Button variant="outline" disabled={busy || inv.resend_count >= MAX_RESENDS}
                      aria-label={`${inv.email_masked} 초대 재전송`}
                      onClick={() => void run(() => service.resend(orgId, inv.invitation_id), '초대를 다시 보냈습니다. 이전 링크는 더 이상 쓸 수 없습니다.', 'resend')}>
                      재전송
                    </Button>
                  )}
                  {inv.status === 'pending' && (
                    <Button variant="outline" disabled={busy} aria-label={`${inv.email_masked} 초대 취소`}
                      onClick={() => void run(() => service.revoke(orgId, inv.invitation_id), '초대를 취소했습니다.', 'revoke')}>
                      취소
                    </Button>
                  )}
                  {inv.status === 'expired' && <span className="company-muted">만료된 초대는 새로 보내 주세요.</span>}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function CompanyConsolePage({ postingsUi = false }: { postingsUi?: boolean }) {
  const service = useCompanyService();
  const { state } = useAuth();
  const navigate = useNavigate();
  const me = (state.status === 'authenticated' ? state.user.userId : undefined) ?? '';
  const [params, setParams] = useSearchParams();
  const mine = useQuery(['my-organizations', me], (signal) => service.myOrganizations(signal));
  const selected = params.get('org');
  const current = mine.status === 'ready' ? mine.data.find((x) => x.organization.organization_id === selected) : undefined;

  const pick = (id: string) => setParams({ org: id });
  const left = () => { mine.retry(); navigate('/company', { replace: true }); };

  return (
    <section className="company-page" aria-labelledby="company-title">
      <h1 id="company-title">기업 콘솔</h1>
      <p className="company-notice" role="note">기업 기능은 승인 전 기능입니다. 가상 데이터(Mock)이며 서버 연동은 없습니다.</p>
      {(mine.status === 'loading' || mine.status === 'idle') && <StatePanel variant="loading" title="내 조직을 불러오는 중입니다" />}
      {mine.status === 'error' && <StatePanel variant="error" title="내 조직을 불러오지 못했습니다" actionLabel="다시 시도" onAction={mine.retry} />}
      {mine.status === 'ready' && (
        <>
          <nav aria-label="내 조직" className="company-orgs">
            {mine.data.length === 0 ? <p className="company-muted">소속된 조직이 없습니다.</p> : (
              <ul>
                {mine.data.map(({ organization: o, role }) => (
                  <li key={o.organization_id}>
                    <Button variant={o.organization_id === selected ? 'primary' : 'outline'}
                      aria-pressed={o.organization_id === selected} onClick={() => pick(o.organization_id)}>
                      {o.name}
                    </Button>
                    <span className="company-muted"> {ROLE_LABELS[role]} · {ORG_STATUS_LABELS[o.status]}</span>
                  </li>
                ))}
              </ul>
            )}
          </nav>
          {selected && !current && (
            <StatePanel variant="error" title="조직을 찾을 수 없거나 접근 권한이 없습니다"
              description="소속이 바뀌었거나 다른 회사의 주소일 수 있습니다." actionLabel="내 조직 목록" onAction={() => setParams({})} />
          )}
          {current && (
            <div className="company-detail" key={current.organization.organization_id}>
              <h2 className="company-org-name">{current.organization.name}
                <span className={`company-badge company-badge--${current.organization.status}`}>{ORG_STATUS_LABELS[current.organization.status]}</span>
              </h2>
              {current.organization.status === 'pending' && (
                <p className="company-notice" role="note">운영 확인 대기 중입니다. 확인 전에는 초대할 수 없고, 공고는 초안만 쓸 수 있습니다.</p>
              )}
              {postingsUi && <Link to={`/company/postings?org=${current.organization.organization_id}`}>공고 관리 (T127)</Link>}
              <Members orgId={current.organization.organization_id} myRole={current.role} me={me} onLeft={left} />
              {current.role === 'owner'
                ? <Invitations orgId={current.organization.organization_id} active={current.organization.status === 'active'} />
                : <p className="company-muted">초대·역할 변경은 기업 관리자만 할 수 있습니다.</p>}
            </div>
          )}
          <RegisterForm onDone={(id) => { mine.retry(); pick(id); }} />
        </>
      )}
    </section>
  );
}
