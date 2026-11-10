import { useState } from 'react';
import { useApi } from '../api/ApiContext';
import type { JobRoleRef } from '../api/catalog';
import type { TargetRole } from '../api/me';
import { useQuery } from '../api/useQuery';
import './MyCareerWorkspace.css';

type Role = JobRoleRef;

const byPriority = (items: TargetRole[]) => [...items].sort((a, b) => a.priority - b.priority).map((x) => x.job_role);

function Feedback({ loading, error, empty }: { loading: boolean; error: string; empty?: string }) {
  if (loading) return <p role="status">불러오는 중…</p>;
  if (error) return <p role="alert">{error}</p>;
  return empty ? <p role="status">{empty}</p> : null;
}

export function TargetRolesPage() {
  const api = useApi();
  const catalog = useQuery(['role-options'], (signal) => api.jobRoles.list({ limit: 100 }, signal));
  const targets = useQuery(['me-target-roles'], (signal) => api.me.targetRoles.list(signal));
  // 화면에서 고친 선택(저장 전). null 이면 서버에 저장된 값을 그대로 보여 줍니다.
  const [draft, setDraft] = useState<Role[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const roles = catalog.status === 'ready' ? catalog.data.items : [];
  const selected = draft ?? (targets.status === 'ready' ? byPriority(targets.data) : []);
  const loading = catalog.status === 'loading' || targets.status === 'loading';
  const loadError = catalog.status === 'error' || targets.status === 'error' ? '목표 직무를 불러오지 못했습니다.' : '';

  const toggle = (role: Role) => {
    if (selected.some((x) => x.job_role_id === role.job_role_id)) return setDraft(selected.filter((x) => x.job_role_id !== role.job_role_id));
    if (selected.length >= 3) return setMessage('목표 직무는 최대 3개까지 선택할 수 있습니다.');
    setDraft([...selected, role]); setMessage('');
  };
  const move = (index: number, direction: number) => {
    const next = [...selected], target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!]; setDraft(next);
  };
  const save = async () => {
    setSaving(true); setMessage('');
    try {
      const saved = await api.me.targetRoles.replace({ items: selected.map((role, index) => ({ job_role_id: role.job_role_id, priority: index + 1 })) });
      targets.setData(() => saved); setDraft(null); setMessage('목표 직무를 저장했습니다.');
    } catch { setMessage('저장하지 못했습니다. 다시 시도해 주세요.'); } finally { setSaving(false); }
  };

  return <section className="career-workspace"><h1>목표 직무 관리</h1><p>최대 3개를 선택하고 우선순위를 정하세요.</p>
    <Feedback loading={loading} error={loadError} />
    {!loading && !loadError && <><div className="career-options">{roles.map((role) => <button key={role.job_role_id} aria-pressed={selected.some((x) => x.job_role_id === role.job_role_id)} onClick={() => toggle(role)}>{role.name}</button>)}</div>
      <ol>{selected.map((role, index) => <li key={role.job_role_id}><strong>{index + 1}순위 · {role.name}</strong><span><button aria-label={`${role.name} 위로`} onClick={() => move(index, -1)}>↑</button><button aria-label={`${role.name} 아래로`} onClick={() => move(index, 1)}>↓</button></span></li>)}</ol>
      <button className="primary" disabled={saving} onClick={() => void save()}>{saving ? '저장 중…' : '저장'}</button>{message && <p role="status">{message}</p>}</>}
  </section>;
}

export function CareerHistoryPage() {
  const api = useApi();
  const history = useQuery(['me-career-history'], async (signal) => {
    const [experiences, projects] = await Promise.all([api.me.experiences.list(signal), api.me.projects.list(signal)]);
    return { experiences, projects };
  });
  const [kind, setKind] = useState<'experience' | 'project'>('experience'); const [title, setTitle] = useState(''); const [organization, setOrganization] = useState('');
  const [actionError, setActionError] = useState('');

  const loading = history.status === 'loading';
  const error = history.status === 'error' ? '경력 정보를 불러오지 못했습니다.' : actionError;
  const experiences = history.status === 'ready' ? history.data.experiences : [];
  const projects = history.status === 'ready' ? history.data.projects : [];

  const add = async () => {
    if (!title.trim() || (kind === 'experience' && !organization.trim())) return setActionError('필수 항목을 입력해 주세요.');
    try {
      if (kind === 'experience') {
        const item = await api.me.experiences.create({ organization, title });
        history.setData((d) => ({ ...d, experiences: [...d.experiences, item] }));
      } else {
        const item = await api.me.projects.create({ title, summary: organization || null, skill_ids: [] });
        history.setData((d) => ({ ...d, projects: [...d.projects, item] }));
      }
      setTitle(''); setOrganization(''); setActionError('');
    } catch { setActionError('등록하지 못했습니다.'); }
  };
  const remove = async (type: 'experiences' | 'projects', id: string) => {
    try {
      if (type === 'experiences') {
        await api.me.experiences.remove(id);
        history.setData((d) => ({ ...d, experiences: d.experiences.filter((x) => x.experience_id !== id) }));
      } else {
        await api.me.projects.remove(id);
        history.setData((d) => ({ ...d, projects: d.projects.filter((x) => x.project_id !== id) }));
      }
    } catch { setActionError('삭제하지 못했습니다.'); }
  };
  const empty = !loading && !error && experiences.length === 0 && projects.length === 0;
  return <section className="career-workspace"><h1>경력·프로젝트</h1><Feedback loading={loading} error={error} empty={empty ? '등록한 경력이나 프로젝트가 없습니다.' : undefined} />
    {!loading && <><div className="career-form"><label>유형<select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="experience">경력</option><option value="project">프로젝트</option></select></label><label>{kind === 'experience' ? '회사·기관' : '프로젝트 요약'}<input value={organization} onChange={(e) => setOrganization(e.target.value)} /></label><label>{kind === 'experience' ? '직무' : '프로젝트명'}<input value={title} onChange={(e) => setTitle(e.target.value)} /></label><button className="primary" onClick={() => void add()}>추가</button></div>
      <ul>{experiences.map((x) => <li key={x.experience_id}><span><strong>경력</strong> · {x.organization} · {x.title}</span><button onClick={() => void remove('experiences', x.experience_id)}>삭제</button></li>)}{projects.map((x) => <li key={x.project_id}><span><strong>프로젝트</strong> · {x.title}{x.summary && ` · ${x.summary}`}</span><button onClick={() => void remove('projects', x.project_id)}>삭제</button></li>)}</ul></>}
  </section>;
}

export function BookmarksPage() {
  const api = useApi();
  const bookmarks = useQuery(['me-bookmarks'], (signal) => api.me.bookmarks.list(signal));
  const [actionError, setActionError] = useState('');
  const loading = bookmarks.status === 'loading';
  const error = bookmarks.status === 'error' ? '저장한 공고를 불러오지 못했습니다.' : actionError;
  const items = bookmarks.status === 'ready' ? bookmarks.data.items : [];
  const remove = async (id: string) => {
    try {
      await api.me.bookmarks.remove(id);
      bookmarks.setData((page) => ({ ...page, items: page.items.filter((x) => x.job_posting_id !== id) }));
    } catch { setActionError('저장을 해제하지 못했습니다.'); }
  };
  return <section className="career-workspace"><h1>저장한 채용공고</h1><Feedback loading={loading} error={error} empty={!loading && !error && items.length === 0 ? '저장한 공고가 없습니다.' : undefined} />
    <ul>{items.map((item) => <li key={item.job_posting_id}><span><strong>{item.title}</strong> · {item.company.name}{item.status === 'closed' && <em> 마감된 공고</em>}</span><button onClick={() => void remove(item.job_posting_id)}>저장 해제</button></li>)}</ul>
  </section>;
}
