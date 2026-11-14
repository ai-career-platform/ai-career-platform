/**
 * 기업 채용공고 관리 콘솔 (T127, UI 제안 UI-N08). 상태 기계 T125(PROPOSED), 서버 T126(플래그 뒤).
 * - 목록(상태별 필터) → 선택한 공고 상세: 초안·반려는 편집, 검수 대기는 철회만, 게시 중은 마감·수정본, 종료 상태는 보기만.
 * - 기업은 **검수 요청까지만** 할 수 있습니다. 게시·반려·내림은 운영자 검수 결과로만 바뀝니다(화면에 버튼 없음).
 * - 저장은 응답으로 목록을 바로 고치고, 409(다른 사람이 먼저 바꿈)·404 이면 최신 목록을 다시 불러옵니다.
 */
import { useId, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ApiError } from '../api/errors';
import {
  EMPLOYMENT_LABELS, MAX_PUBLISH_DAYS, POSTING_STATUSES, REASON_LABELS, STATUS_LABELS, type EmploymentType, type Posting,
  type PostingFields, type PostingStatus,
} from '../api/companyPostings';
import { useQuery } from '../api/useQuery';
import { useCompanyService } from '../company/companyContext';
import { usePostingService } from '../company/postingContext';
import { Button } from '../components/Button';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { StatePanel } from '../components/StatePanel';
import { env } from '../config/env';
import './CompanyConsolePage.css';

function trouble(error: unknown, action: string): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 403) return '운영 확인이 끝난 조직만 검수를 요청할 수 있습니다.';
    if (error.status === 404) return '공고를 찾을 수 없거나 접근 권한이 없습니다.';
    if (error.status === 409) return '다른 사람이 먼저 바꿨거나 지금 상태에서는 할 수 없습니다. 최신 내용을 불러왔습니다.';
    if (error.status === 422) return '필수 항목(제목·설명·고용형태·근무지·마감일)을 채우고, 지원 링크는 https 주소로 입력해 주세요.';
    if (error.status === 503) return '공고 관리 기능을 지금 쓸 수 없습니다. 잠시 후 다시 시도해 주세요.';
  }
  return `${action}하지 못했습니다.`;
}
const dateText = (iso: string | null) => (iso ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeZone: 'Asia/Seoul' })
  .format(new Date(iso)) : '—');
const toDateInput = (iso: string | null) => (iso ? iso.slice(0, 10) : '');
const fromDateInput = (value: string) => (value ? new Date(`${value}T23:59:00+09:00`).toISOString() : null);

function Editor({ posting, busy, onSave }: { posting: Posting; busy: boolean; onSave: (fields: PostingFields) => void }) {
  const id = useId();
  const [form, setForm] = useState({
    title: posting.title, description: posting.description ?? '', employment_type: posting.employment_type ?? '',
    location_text: posting.location_text ?? '', apply_url: posting.apply_url ?? '', expires: toDateInput(posting.expires_at),
  });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  function submit(event: FormEvent) {
    event.preventDefault();
    onSave({ title: form.title, description: form.description || null,
      employment_type: (form.employment_type || null) as EmploymentType | null, location_text: form.location_text || null,
      apply_url: form.apply_url || null, expires_at: fromDateInput(form.expires) });
  }
  return (
    <form className="company-form" onSubmit={submit} aria-label="공고 편집">
      <label htmlFor={`${id}-title`}>제목 (필수)</label>
      <input id={`${id}-title`} value={form.title} maxLength={240} required onChange={set('title')} />
      <label htmlFor={`${id}-desc`}>직무 설명 (필수)</label>
      <textarea id={`${id}-desc`} value={form.description} rows={5} maxLength={20000} onChange={set('description')}
        aria-describedby={`${id}-desc-hint`} />
      <p id={`${id}-desc-hint`} className="company-muted">개인 휴대전화·개인 이메일, 성별·연령 같은 직무와 무관한 조건은 적지 마세요(반려 사유).</p>
      <label htmlFor={`${id}-type`}>고용형태 (필수)</label>
      <select id={`${id}-type`} value={form.employment_type} onChange={set('employment_type')}>
        <option value="">선택</option>
        {Object.entries(EMPLOYMENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <label htmlFor={`${id}-loc`}>근무지 (필수)</label>
      <input id={`${id}-loc`} value={form.location_text} maxLength={120} onChange={set('location_text')} />
      <label htmlFor={`${id}-url`}>지원 링크 (https)</label>
      <input id={`${id}-url`} type="url" value={form.apply_url} maxLength={500} onChange={set('apply_url')} />
      <label htmlFor={`${id}-exp`}>마감일 (필수, 게시일부터 최대 {MAX_PUBLISH_DAYS}일)</label>
      <input id={`${id}-exp`} type="date" value={form.expires} onChange={set('expires')} />
      <Button type="submit" disabled={busy || !form.title.trim()}>저장</Button>
    </form>
  );
}

export function CompanyPostingsPage() {
  const companies = useCompanyService();
  const service = usePostingService();
  const [params, setParams] = useSearchParams();
  const orgId = params.get('org') ?? '';
  const selectedId = params.get('posting');
  const mine = useQuery(['my-organizations-for-postings'], (signal) => companies.myOrganizations(signal));
  const list = useQuery(orgId ? ['company-postings', orgId] : null, (signal) => service.list(orgId, signal));
  const [filter, setFilter] = useState<PostingStatus | 'all'>('all');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [closing, setClosing] = useState<Posting | null>(null);
  const [newTitle, setNewTitle] = useState('');

  const org = mine.status === 'ready' ? mine.data.find((x) => x.organization.organization_id === orgId) : undefined;
  const postings = list.status === 'ready' ? list.data : [];
  const shown = filter === 'all' ? postings : postings.filter((p) => p.status === filter);
  const selected = postings.find((p) => p.posting_id === selectedId);
  const open = (id: string) => setParams({ org: orgId, posting: id });

  async function run(action: () => Promise<Posting>, ok: string, verb: string) {
    setBusy(true); setMessage(null);
    try {
      const saved = await action();
      list.setData((rows) => (rows.some((r) => r.posting_id === saved.posting_id)
        ? rows.map((r) => (r.posting_id === saved.posting_id ? saved : r)) : [saved, ...rows]));
      setMessage({ kind: 'ok', text: ok });
      return saved;
    } catch (error) {
      setMessage({ kind: 'error', text: trouble(error, verb) });
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) list.retry();
      return null;
    } finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    const saved = await run(() => service.create(orgId, { title: newTitle }), '초안을 만들었습니다. 나머지 항목을 채운 뒤 검수를 요청하세요.', '초안을 만들');
    if (saved) { setNewTitle(''); open(saved.posting_id); }
  }

  if (!orgId) {
    return (
      <section className="company-page" aria-labelledby="postings-title">
        <h1 id="postings-title">공고 관리</h1>
        <StatePanel variant="empty" title="조직을 먼저 고르세요" description="기업 콘솔에서 조직을 고른 뒤 공고 관리로 들어오세요." />
        <Link to="/company">기업 콘솔로 이동</Link>
      </section>
    );
  }
  return (
    <section className="company-page" aria-labelledby="postings-title">
      <h1 id="postings-title">공고 관리{org ? ` — ${org.organization.name}` : ''}</h1>
      <p className="company-notice" role="note">기업은 <strong>검수 요청까지만</strong> 할 수 있습니다. 운영자가 검수해 승인해야 공개 공고 목록에 나옵니다.{env.mockEnabled ? ' 가상 데이터(Mock)입니다.' : ''}</p>
      <Link to={`/company?org=${orgId}`}>← 기업 콘솔</Link>
      {message && <p className={message.kind === 'error' ? 'company-error' : 'company-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}
      {(list.status === 'loading' || list.status === 'idle') && <StatePanel variant="loading" title="공고를 불러오는 중입니다" />}
      {list.status === 'error' && (
        list.error instanceof ApiError && list.error.status === 404
          ? <StatePanel variant="error" title="조직을 찾을 수 없거나 접근 권한이 없습니다" description="소속이 바뀌었거나 다른 회사의 주소일 수 있습니다." />
          : <StatePanel variant="error" title="공고를 불러오지 못했습니다" actionLabel="다시 시도" onAction={list.retry} />
      )}
      {list.status === 'ready' && (
        <>
          <form className="company-form company-form--inline" onSubmit={(e) => void create(e)}>
            <label htmlFor="new-posting-title">새 공고 제목</label>
            <input id="new-posting-title" value={newTitle} maxLength={240} onChange={(e) => setNewTitle(e.target.value)} />
            <Button type="submit" disabled={busy || !newTitle.trim()}>초안 만들기</Button>
          </form>
          <div className="company-actions" role="group" aria-label="상태로 거르기">
            {(['all', ...POSTING_STATUSES] as const).map((s) => (
              <Button key={s} variant={filter === s ? 'primary' : 'outline'} aria-pressed={filter === s} onClick={() => setFilter(s)}>
                {s === 'all' ? `전체 ${postings.length}` : `${STATUS_LABELS[s]} ${postings.filter((p) => p.status === s).length}`}
              </Button>
            ))}
          </div>
          {shown.length === 0 ? <p className="company-muted">해당하는 공고가 없습니다.</p> : (
            <div className="company-table-wrap">
              <table className="company-table">
                <caption>공고 {shown.length}건</caption>
                <thead><tr><th scope="col">제목</th><th scope="col">상태</th><th scope="col">마감일</th><th scope="col">보기</th></tr></thead>
                <tbody>
                  {shown.map((p) => (
                    <tr key={`${p.posting_id}:${p.version}`}>
                      <th scope="row">{p.title}{p.revision_of && <span className="company-muted"> (수정본)</span>}</th>
                      <td><span className={`company-badge company-badge--${p.status}`}>{STATUS_LABELS[p.status]}</span></td>
                      <td>{dateText(p.expires_at)}</td>
                      <td><Button variant="outline" onClick={() => open(p.posting_id)} aria-label={`${p.title} 열기`}>열기</Button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selectedId && !selected && <StatePanel variant="error" title="공고를 찾을 수 없거나 접근 권한이 없습니다" />}
          {selected && (
            <section className="company-section" aria-labelledby="posting-detail-title" key={`${selected.posting_id}:${selected.version}`}>
              <h2 id="posting-detail-title">{selected.title} <span className={`company-badge company-badge--${selected.status}`}>{STATUS_LABELS[selected.status]}</span></h2>
              {selected.status === 'rejected' && (
                <div className="company-notice" role="note">
                  <p><strong>반려 사유: {REASON_LABELS[selected.reason_code ?? 'other'] ?? selected.reason_code}</strong></p>
                  {selected.reason_note && <p>{selected.reason_note}</p>}
                  <p>고쳐서 저장하면 초안으로 돌아가고, 다시 검수를 요청할 수 있습니다.</p>
                </div>
              )}
              {selected.status === 'taken_down' && selected.reason_code && (
                <p className="company-notice" role="note">운영 내림 사유: {REASON_LABELS[selected.reason_code] ?? selected.reason_code}</p>
              )}
              {(selected.status === 'draft' || selected.status === 'rejected') && (
                <>
                  <Editor posting={selected} busy={busy}
                    onSave={(fields) => void run(() => service.edit(orgId, selected.posting_id, fields, selected.version), '저장했습니다.', '저장')} />
                  {selected.status === 'draft' && (
                    <Button disabled={busy} onClick={() => void run(() => service.submit(orgId, selected.posting_id, selected.version),
                      '검수를 요청했습니다. 운영자가 확인한 뒤 게시됩니다.', '검수 요청')}>검수 요청</Button>
                  )}
                </>
              )}
              {selected.status === 'pending_review' && (
                <>
                  <p>검수 대기 중입니다. 내용을 고치려면 요청을 철회하세요.</p>
                  <Button variant="outline" disabled={busy} onClick={() => void run(() => service.withdraw(orgId, selected.posting_id, selected.version),
                    '검수 요청을 철회했습니다. 초안으로 돌아갔습니다.', '철회')}>검수 요청 철회</Button>
                </>
              )}
              {selected.status === 'published' && (
                <div className="company-actions">
                  <Button variant="outline" disabled={busy}
                    onClick={() => void run(() => service.revise(orgId, selected.posting_id), '수정본을 만들었습니다. 승인되기 전까지 공개 공고는 그대로입니다.', '수정본을 만들')
                      .then((rev) => rev && open(rev.posting_id))}>수정본 만들기</Button>
                  <Button variant="outline" disabled={busy} onClick={() => setClosing(selected)}>마감</Button>
                </div>
              )}
              {['closed', 'expired', 'taken_down'].includes(selected.status) && (
                <p className="company-muted">종료된 공고입니다. 다시 올리려면 새 초안을 만드세요.</p>
              )}
              <dl className="company-muted">
                <dt>마감일</dt><dd>{dateText(selected.expires_at)}</dd>
                <dt>지원 링크</dt><dd>{selected.apply_url ?? '—'}</dd>
              </dl>
            </section>
          )}
        </>
      )}
      {closing && (
        <ConfirmDialog title="공고를 마감할까요?" confirmLabel="마감" pending={busy} onClose={() => setClosing(null)}
          onConfirm={() => void run(() => service.close(orgId, closing.posting_id, closing.version), '공고를 마감했습니다. 공개 목록에서 바로 내려갑니다.', '마감')
            .then(() => setClosing(null))}>
          <p>‘{closing.title}’을(를) 마감하면 공개 공고 목록에서 바로 내려가고 되돌릴 수 없습니다.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
