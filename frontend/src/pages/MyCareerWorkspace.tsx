import { useCallback, useEffect, useState } from 'react';
import { useApi } from '../api/ApiContext';
import type { JobPostingSummary, JobRoleRef } from '../api/catalog';
import type { Experience, Project } from '../api/me';
import './MyCareerWorkspace.css';

type Role = JobRoleRef;

function Feedback({ loading, error, empty }: { loading: boolean; error: string; empty?: string }) {
  if (loading) return <p role="status">불러오는 중…</p>;
  if (error) return <p role="alert">{error}</p>;
  return empty ? <p role="status">{empty}</p> : null;
}

export function TargetRolesPage() {
  const api = useApi();
  const [roles, setRoles] = useState<Role[]>([]);
  const [selected, setSelected] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setMessage('');
    try {
      const [catalog, targets] = await Promise.all([
        api.jobRoles.list({ limit: 100 }), api.me.targetRoles.list(),
      ]);
      setRoles(catalog.items); setSelected(targets.sort((a, b) => a.priority - b.priority).map((x) => x.job_role));
    } catch { setMessage('목표 직무를 불러오지 못했습니다.'); } finally { setLoading(false); }
  }, [api]);
  // oxlint-disable-next-line react/set-state-in-effect -- 최초 API 동기화
  useEffect(() => { void load(); }, [load]);
  const toggle = (role: Role) => {
    if (selected.some((x) => x.job_role_id === role.job_role_id)) return setSelected(selected.filter((x) => x.job_role_id !== role.job_role_id));
    if (selected.length >= 3) return setMessage('목표 직무는 최대 3개까지 선택할 수 있습니다.');
    setSelected([...selected, role]); setMessage('');
  };
  const move = (index: number, direction: number) => {
    const next = [...selected], target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!]; setSelected(next);
  };
  const save = async () => {
    setSaving(true); setMessage('');
    try {
      const saved = await api.me.targetRoles.replace({ items: selected.map((role, index) => ({ job_role_id: role.job_role_id, priority: index + 1 })) });
      setSelected(saved.sort((a, b) => a.priority - b.priority).map((x) => x.job_role)); setMessage('목표 직무를 저장했습니다.');
    } catch { setMessage('저장하지 못했습니다. 다시 시도해 주세요.'); } finally { setSaving(false); }
  };
  const loadError = !loading && message.includes('불러오지') ? message : '';
  return <main className="career-workspace"><h1>목표 직무 관리</h1><p>최대 3개를 선택하고 우선순위를 정하세요.</p>
    <Feedback loading={loading} error={loadError} />
    {!loading && !loadError && <><div className="career-options">{roles.map((role) => <button key={role.job_role_id} aria-pressed={selected.some((x) => x.job_role_id === role.job_role_id)} onClick={() => toggle(role)}>{role.name}</button>)}</div>
      <ol>{selected.map((role, index) => <li key={role.job_role_id}><strong>{index + 1}순위 · {role.name}</strong><span><button aria-label={`${role.name} 위로`} onClick={() => move(index, -1)}>↑</button><button aria-label={`${role.name} 아래로`} onClick={() => move(index, 1)}>↓</button></span></li>)}</ol>
      <button className="primary" disabled={saving} onClick={() => void save()}>{saving ? '저장 중…' : '저장'}</button>{message && <p role="status">{message}</p>}</>}
  </main>;
}

export function CareerHistoryPage() {
  const api = useApi();
  const [experiences, setExperiences] = useState<Experience[]>([]); const [projects, setProjects] = useState<Project[]>([]);
  const [kind, setKind] = useState<'experience' | 'project'>('experience'); const [title, setTitle] = useState(''); const [organization, setOrganization] = useState('');
  const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = useCallback(async () => { setLoading(true); setError(''); try { const [e, p] = await Promise.all([api.me.experiences.list(), api.me.projects.list()]); setExperiences(e); setProjects(p); } catch { setError('경력 정보를 불러오지 못했습니다.'); } finally { setLoading(false); } }, [api]);
  // oxlint-disable-next-line react/set-state-in-effect -- 최초 API 동기화
  useEffect(() => { void load(); }, [load]);
  const add = async () => {
    if (!title.trim() || (kind === 'experience' && !organization.trim())) return setError('필수 항목을 입력해 주세요.');
    try {
      if (kind === 'experience') { const item = await api.me.experiences.create({ organization, title }); setExperiences([...experiences, item]); }
      else { const item = await api.me.projects.create({ title, summary: organization || null, skill_ids: [] }); setProjects([...projects, item]); }
      setTitle(''); setOrganization(''); setError('');
    } catch { setError('등록하지 못했습니다.'); }
  };
  const remove = async (type: 'experiences' | 'projects', id: string) => { try { await (type === 'experiences' ? api.me.experiences.remove(id) : api.me.projects.remove(id)); if (type === 'experiences') setExperiences(experiences.filter((x) => x.experience_id !== id)); else setProjects(projects.filter((x) => x.project_id !== id)); } catch { setError('삭제하지 못했습니다.'); } };
  const empty = !loading && !error && experiences.length === 0 && projects.length === 0;
  return <main className="career-workspace"><h1>경력·프로젝트</h1><Feedback loading={loading} error={error} empty={empty ? '등록한 경력이나 프로젝트가 없습니다.' : undefined} />
    {!loading && <><div className="career-form"><label>유형<select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="experience">경력</option><option value="project">프로젝트</option></select></label><label>{kind === 'experience' ? '회사·기관' : '프로젝트 요약'}<input value={organization} onChange={(e) => setOrganization(e.target.value)} /></label><label>{kind === 'experience' ? '직무' : '프로젝트명'}<input value={title} onChange={(e) => setTitle(e.target.value)} /></label><button className="primary" onClick={() => void add()}>추가</button></div>
      <ul>{experiences.map((x) => <li key={x.experience_id}><span><strong>경력</strong> · {x.organization} · {x.title}</span><button onClick={() => void remove('experiences', x.experience_id)}>삭제</button></li>)}{projects.map((x) => <li key={x.project_id}><span><strong>프로젝트</strong> · {x.title}{x.summary && ` · ${x.summary}`}</span><button onClick={() => void remove('projects', x.project_id)}>삭제</button></li>)}</ul></>}
  </main>;
}

export function BookmarksPage() {
  const api = useApi(); const [items, setItems] = useState<JobPostingSummary[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = useCallback(async () => { try { const page = await api.me.bookmarks.list(); setItems(page.items); } catch { setError('저장한 공고를 불러오지 못했습니다.'); } finally { setLoading(false); } }, [api]);
  // oxlint-disable-next-line react/set-state-in-effect -- 최초 API 동기화
  useEffect(() => { void load(); }, [load]);
  const remove = async (id: string) => { try { await api.me.bookmarks.remove(id); setItems(items.filter((x) => x.job_posting_id !== id)); } catch { setError('저장을 해제하지 못했습니다.'); } };
  return <main className="career-workspace"><h1>저장한 채용공고</h1><Feedback loading={loading} error={error} empty={!loading && !error && items.length === 0 ? '저장한 공고가 없습니다.' : undefined} />
    <ul>{items.map((item) => <li key={item.job_posting_id}><span><strong>{item.title}</strong> · {item.company.name}{item.status === 'closed' && <em> 마감된 공고</em>}</span><button onClick={() => void remove(item.job_posting_id)}>저장 해제</button></li>)}</ul>
  </main>;
}
