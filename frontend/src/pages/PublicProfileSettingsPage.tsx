/**
 * 공개 포트폴리오 편집·미리보기 (T130, UI 제안 UI-N07). 정책 T128(PROPOSED), 서버 T129(플래그 뒤).
 * 흐름: 항목 선택 → 저장 → **미리보기 확인** → 확인 대화상자(위험 안내 동의) → 공유 링크 만들기 → 회수·전체 철회.
 * - 모든 항목은 비공개가 기본입니다. 선택을 바꾸면 이전 확인이 풀리고 기존 링크는 다시 확인할 때까지 열리지 않습니다.
 * - 링크 주소는 만들 때 한 번만 보여 줍니다. 지금은 Mock Adapter 만 연결됩니다.
 */
import { useId, useState } from 'react';
import { Link } from 'react-router';
import { ApiError } from '../api/errors';
import {
  FIELD_LABELS, MAX_ACTIVE_LINKS, NEVER_LABELS, TTL_CHOICES, type CreatedLink, type PublishableField,
  type Selection, type ShareLink,
} from '../api/publicPortfolio';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { StatePanel } from '../components/StatePanel';
import { usePortfolioService } from '../portfolio/portfolioContext';
import { PublicProfileView } from '../portfolio/PublicProfileView';
import './PublicPortfolio.css';

const GROUPS: { title: string; fields: PublishableField[] }[] = [
  { title: '기본 정보', fields: ['display_name', 'headline', 'bio', 'location_text'] },
  { title: '경력에서 보일 내용', fields: ['experience.organization', 'experience.title', 'experience.period', 'experience.description'] },
  { title: '프로젝트에서 보일 내용', fields: ['project.title', 'project.summary', 'project.period'] },
  { title: '기술·희망 직무', fields: ['skills', 'target_roles'] },
];
const day = (iso: string) => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeZone: 'Asia/Seoul' }).format(new Date(iso));

function problem(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 409) return '다른 곳에서 먼저 바뀌었거나, 공개 확인 전이거나, 링크가 이미 3개입니다. 최신 상태를 다시 불러왔습니다.';
    if (error.status === 404) return '대상을 찾을 수 없습니다.';
    if (error.status === 422) return '입력값을 확인해 주세요.';
  }
  return '처리하지 못했습니다.';
}

type Draft = { fields: Set<PublishableField>; exp: Set<string>; proj: Set<string>; alias: string };
const draftOf = (s: Selection): Draft => ({ fields: new Set(s.fields), exp: new Set(s.experience_ids), proj: new Set(s.project_ids), alias: s.alias ?? '' });

export function PublicProfileSettingsPage() {
  const service = usePortfolioService();
  const { state } = useAuth();
  const me = state.status === 'authenticated' ? state.user.userId : null;
  const id = useId();
  const settings = useQuery(['public-profile', me], (signal) => service.settings(signal));
  const items = useQuery(['public-profile-items', me], (signal) => service.ownItems(signal));
  const [previewKey, setPreviewKey] = useState(0);
  const preview = useQuery(['public-profile-preview', me, previewKey], (signal) => service.preview(signal));
  // 편집 중인 선택(null 이면 서버에 저장된 선택을 그대로 보여 줌)
  const [edit, setEdit] = useState<Draft | null>(null);
  // 만료 계산 기준 시각(렌더 중 Date 호출 금지 — 저장·불러오기 때 갱신)
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [understood, setUnderstood] = useState(false);
  const [created, setCreated] = useState<CreatedLink | null>(null);
  const [ttl, setTtl] = useState<number>(30);
  const [revoking, setRevoking] = useState<ShareLink | null>(null);
  const [withdrawing, setWithdrawing] = useState(false);

  const selection = settings.status === 'ready' ? settings.data.selection : null;
  const draft = edit ?? (selection ? draftOf(selection) : null);
  const setDraft = (next: Draft) => setEdit(next);

  /**
   * 저장 응답으로 화면 데이터를 바로 고칩니다(apply) — 다시 불러오면 화면 전체가 잠깐 사라져 포커스를 잃기 때문.
   * 실패했거나 reload 가 필요한 동작(전체 중단)만 서버 상태를 다시 불러옵니다.
   */
  async function run<T>(action: () => Promise<T>, ok: string, apply?: (result: T) => void, reload = false) {
    setBusy(true); setMessage(null);
    try {
      const result = await action();
      apply?.(result);
      setMessage({ kind: 'ok', text: ok });
      setEdit(null);
      if (reload) settings.retry();
      return true;
    } catch (error) {
      setMessage({ kind: 'error', text: problem(error) });
      settings.retry();
      return false;
    } finally {
      setBusy(false); setPreviewKey((k) => k + 1); setNow(Date.now());
    }
  }
  const putSelection = (next: Selection) => settings.setData((s) => ({ ...s, selection: next }));
  const toggle = <T,>(set: Set<T>, value: T) => { const next = new Set(set); if (next.has(value)) next.delete(value); else next.add(value); return next; };
  const dirty = !!(edit && draft && selection && (
    [...draft.fields].sort().join() !== [...selection.fields].sort().join()
    || [...draft.exp].sort().join() !== [...selection.experience_ids].sort().join()
    || [...draft.proj].sort().join() !== [...selection.project_ids].sort().join()
    || draft.alias.trim() !== (selection.alias ?? '')));
  const linkState = (l: ShareLink) => (l.revoked ? '회수됨' : new Date(l.expires_at).getTime() <= now ? '만료' : '사용 중');
  const activeLinks = settings.status === 'ready' ? settings.data.links.filter((l) => linkState(l) === '사용 중').length : 0;

  return (
    <section className="portfolio-page" aria-labelledby={`${id}-title`}>
      <h1 id={`${id}-title`}>공개 포트폴리오</h1>
      <div className="portfolio-notice" role="note">
        <p><strong>모든 항목은 비공개가 기본입니다.</strong> 고른 항목만, 내가 만든 링크를 받은 사람에게만 보입니다. 검색엔진·기업 검색에는 나오지 않습니다.</p>
        <p>가상 데이터(Mock)입니다. 서버 연동은 아직 없습니다.</p>
      </div>
      {message && <p className={message.kind === 'error' ? 'portfolio-error' : 'portfolio-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}
      {(settings.status === 'loading' || settings.status === 'idle') && <StatePanel variant="loading" title="공개 설정을 불러오는 중입니다" />}
      {settings.status === 'error' && <StatePanel variant="error" title="공개 설정을 불러오지 못했습니다" actionLabel="다시 시도" onAction={settings.retry} />}
      {settings.status === 'ready' && draft && selection && (
        <>
          <form className="portfolio-section" aria-labelledby={`${id}-pick`}
            onSubmit={(e) => { e.preventDefault(); void run(() => service.updateSelection({ fields: [...draft.fields], experience_ids: [...draft.exp],
              project_ids: [...draft.proj], alias: draft.alias.trim() || null, version: selection.version }),
              '선택을 저장했습니다. 아래 미리보기를 확인한 뒤 공개를 확정하세요.', putSelection); }}>
            <h2 id={`${id}-pick`}>1. 공개할 항목 고르기</h2>
            {GROUPS.map((group) => (
              <fieldset key={group.title} className="portfolio-fieldset">
                <legend>{group.title}</legend>
                {group.fields.map((field) => (
                  <label key={field} className="portfolio-check">
                    <input type="checkbox" checked={draft.fields.has(field)} disabled={busy}
                      onChange={() => setDraft({ ...draft, fields: toggle(draft.fields, field) })} />
                    {FIELD_LABELS[field]}
                  </label>
                ))}
                {group.fields.includes('display_name') && draft.fields.has('display_name') && (
                  <label className="portfolio-alias">별칭(비우면 가입 이름)
                    <input value={draft.alias} maxLength={50} disabled={busy} onChange={(e) => setDraft({ ...draft, alias: e.target.value })} />
                  </label>
                )}
              </fieldset>
            ))}
            {items.status === 'ready' && (
              <fieldset className="portfolio-fieldset">
                <legend>공개할 경력·프로젝트 (새로 추가한 항목은 비공개로 시작)</legend>
                {items.data.experiences.map((e) => (
                  <label key={e.id} className="portfolio-check">
                    <input type="checkbox" checked={draft.exp.has(e.id)} disabled={busy} onChange={() => setDraft({ ...draft, exp: toggle(draft.exp, e.id) })} />
                    경력: {e.label}
                  </label>
                ))}
                {items.data.projects.map((p) => (
                  <label key={p.id} className="portfolio-check">
                    <input type="checkbox" checked={draft.proj.has(p.id)} disabled={busy} onChange={() => setDraft({ ...draft, proj: toggle(draft.proj, p.id) })} />
                    프로젝트: {p.label}
                  </label>
                ))}
              </fieldset>
            )}
            <p className="portfolio-muted">공개할 수 없는 항목: {Object.values(NEVER_LABELS).join(', ')}.</p>
            <Button type="submit" disabled={busy || !dirty}>선택 저장</Button>
          </form>

          <section className="portfolio-section" aria-labelledby={`${id}-preview`}>
            <h2 id={`${id}-preview`}>2. 미리보기 — 링크를 받은 사람에게 이렇게 보입니다</h2>
            {dirty && <p className="portfolio-notice" role="note">저장하지 않은 변경이 있습니다. 미리보기는 저장된 선택 기준입니다.</p>}
            {preview.status === 'ready' && <div className="portfolio-preview"><PublicProfileView profile={preview.data} headingLevel={3} /></div>}
            {preview.status === 'error' && <StatePanel variant="error" title="미리보기를 불러오지 못했습니다" actionLabel="다시 시도" onAction={preview.retry} />}
            <p>상태: <strong>{selection.consented ? '공개 확정됨' : selection.fields.length ? '공개 확인 전(링크가 열리지 않음)' : '비공개'}</strong></p>
            <Button disabled={busy || dirty || selection.consented || !selection.fields.length}
              onClick={() => { setUnderstood(false); setConfirming(true); }}>이대로 공개 확정</Button>
          </section>

          <section className="portfolio-section" aria-labelledby={`${id}-links`}>
            <h2 id={`${id}-links`}>3. 공유 링크</h2>
            {!selection.consented && <p className="portfolio-muted">공개를 확정해야 링크를 만들 수 있습니다.</p>}
            <div className="portfolio-row">
              <label htmlFor={`${id}-ttl`}>사용 기간</label>
              <select id={`${id}-ttl`} value={ttl} disabled={!selection.consented} onChange={(e) => setTtl(Number(e.target.value))}>
                {TTL_CHOICES.map((d) => <option key={d} value={d}>{d}일</option>)}
              </select>
              <Button disabled={busy || !selection.consented || activeLinks >= MAX_ACTIVE_LINKS}
                onClick={() => void run(() => service.createLink(ttl), '공유 링크를 만들었습니다.', (link) => {
                  setCreated(link);
                  const { url: _url, notice: _notice, ...row } = link;
                  settings.setData((s) => ({ ...s, links: [row, ...s.links] }));
                })}>공유 링크 만들기</Button>
            </div>
            {created && (
              <div className="portfolio-created" role="note">
                <p><strong>{created.notice}</strong> 필요하면 지금 복사해 두세요.</p>
                <label htmlFor={`${id}-url`}>공유 주소</label>
                <input id={`${id}-url`} readOnly value={`${window.location.origin}${created.url}`} onFocus={(e) => e.currentTarget.select()} />
                <Link to={created.url}>공개 화면 보기(받는 사람에게 보이는 모습)</Link>
              </div>
            )}
            {settings.data.links.length > 0 && (
              <ul className="portfolio-links">
                {settings.data.links.map((l) => {
                  const label = linkState(l);
                  return (
                    <li key={l.link_id}>
                      <span>{day(l.created_at)} 만듦 · {day(l.expires_at)}까지 · 열람 {l.views}회 · <strong>{label}</strong></span>
                      {label === '사용 중' && (
                        <Button variant="outline" disabled={busy} aria-label={`${day(l.created_at)}에 만든 링크 회수`} onClick={() => setRevoking(l)}>회수</Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="portfolio-section" aria-labelledby={`${id}-stop`}>
            <h2 id={`${id}-stop`}>공개 전체 중단</h2>
            <p className="portfolio-muted">모든 링크가 바로 닫히고, 고른 항목이 모두 비공개로 돌아갑니다.</p>
            <Button variant="outline" disabled={busy || (!selection.fields.length && !settings.data.links.some((l) => !l.revoked))}
              onClick={() => setWithdrawing(true)}>공개 중단(동의 철회)</Button>
          </section>
        </>
      )}

      {confirming && selection && (
        <ConfirmDialog title="이 내용을 공개할까요?" confirmLabel="공개 확정" pending={busy} confirmDisabled={!understood}
          onClose={() => setConfirming(false)}
          onConfirm={() => void run(() => service.confirm(selection.version), '공개를 확정했습니다. 이제 공유 링크를 만들 수 있습니다.', putSelection).then(() => setConfirming(false))}>
          <p>공개 항목: {selection.fields.map((f) => FIELD_LABELS[f]).join(', ')}</p>
          <ul>
            <li>링크를 받은 사람은 누구나 볼 수 있고, 다른 사람에게 전달할 수 있습니다.</li>
            <li>링크를 회수하거나 공개를 중단해도, 이미 저장·캡처된 내용은 되돌릴 수 없습니다.</li>
            <li>검색엔진에는 노출하지 않습니다. 기업이 나를 검색할 수 없습니다.</li>
          </ul>
          <label className="portfolio-check"><input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />위 내용을 이해했습니다</label>
        </ConfirmDialog>
      )}
      {revoking && (
        <ConfirmDialog title="이 링크를 회수할까요?" confirmLabel="회수" pending={busy} onClose={() => setRevoking(null)}
          onConfirm={() => void run(() => service.revokeLink(revoking.link_id), '링크를 회수했습니다. 이 주소로는 더 이상 볼 수 없습니다.',
            () => settings.setData((s) => ({ ...s, links: s.links.map((l) => (l.link_id === revoking.link_id ? { ...l, revoked: true } : l)) }))).then(() => setRevoking(null))}>
          <p>회수하면 이 주소로 바로 볼 수 없게 됩니다.</p>
        </ConfirmDialog>
      )}
      {withdrawing && (
        <ConfirmDialog title="공개를 모두 중단할까요?" confirmLabel="공개 중단" pending={busy} onClose={() => setWithdrawing(false)}
          onConfirm={() => void run(() => service.withdraw(), '공개를 중단했습니다. 모든 링크가 닫혔습니다.', () => setCreated(null), true).then(() => setWithdrawing(false))}>
          <p>모든 링크가 바로 닫히고 고른 항목이 초기화됩니다.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
