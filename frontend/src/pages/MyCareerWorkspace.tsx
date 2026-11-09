import { useState } from 'react';
import './MyCareerWorkspace.css';

type Target = { id: string; name: string };
type History = { id: string; kind: '경력' | '프로젝트'; title: string; organization: string };
type Bookmark = { id: string; title: string; company: string; expired?: boolean };

const roles: Target[] = [
  { id: 'backend', name: '백엔드 개발자' }, { id: 'frontend', name: '프론트엔드 개발자' },
  { id: 'data', name: '데이터 엔지니어' },
];
const initialBookmarks: Bookmark[] = [
  { id: 'job-1', title: '주니어 Backend Engineer', company: '가상 테크' },
  { id: 'job-2', title: 'Frontend Developer', company: '샘플 랩', expired: true },
];

export function TargetRolesPage() {
  const [selected, setSelected] = useState<Target[]>([roles[0]!]);
  const [message, setMessage] = useState('');
  const toggle = (role: Target) => {
    if (selected.some((item) => item.id === role.id)) return setSelected(selected.filter((item) => item.id !== role.id));
    if (selected.length >= 3) return setMessage('목표 직무는 최대 3개까지 선택할 수 있습니다.');
    setSelected([...selected, role]); setMessage('');
  };
  const move = (index: number, direction: number) => {
    const next = [...selected], target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!]; setSelected(next);
  };
  return <main className="career-workspace"><h1>목표 직무 관리</h1><p>최대 3개를 선택하고 우선순위를 정하세요.</p>
    <div className="career-options">{roles.map((role) => <button key={role.id} aria-pressed={selected.some((x) => x.id === role.id)} onClick={() => toggle(role)}>{role.name}</button>)}</div>
    <ol>{selected.map((role, index) => <li key={role.id}><strong>{index + 1}순위 · {role.name}</strong><span><button aria-label={`${role.name} 위로`} onClick={() => move(index, -1)}>↑</button><button aria-label={`${role.name} 아래로`} onClick={() => move(index, 1)}>↓</button></span></li>)}</ol>
    <button className="primary" onClick={() => setMessage('목표 직무를 저장했습니다. (Mock)')}>저장</button>{message && <p role="status">{message}</p>}</main>;
}

export function CareerHistoryPage() {
  const [items, setItems] = useState<History[]>([]); const [title, setTitle] = useState(''); const [organization, setOrganization] = useState('');
  const add = () => { if (!title.trim() || !organization.trim()) return; setItems([...items, { id: crypto.randomUUID(), kind: '경력', title, organization }]); setTitle(''); setOrganization(''); };
  return <main className="career-workspace"><h1>경력·프로젝트</h1><div className="career-form"><label>회사·기관<input value={organization} onChange={(e) => setOrganization(e.target.value)} /></label><label>직무·프로젝트명<input value={title} onChange={(e) => setTitle(e.target.value)} /></label><button className="primary" onClick={add}>추가</button></div>
    {items.length === 0 ? <p role="status">등록한 경력이나 프로젝트가 없습니다.</p> : <ul>{items.map((item) => <li key={item.id}><span>{item.organization} · {item.title}</span><button onClick={() => setItems(items.filter((x) => x.id !== item.id))}>삭제</button></li>)}</ul>}</main>;
}

export function BookmarksPage() {
  const [items, setItems] = useState(initialBookmarks);
  return <main className="career-workspace"><h1>저장한 채용공고</h1>{items.length === 0 ? <p role="status">저장한 공고가 없습니다.</p> : <ul>{items.map((item) => <li key={item.id}><span><strong>{item.title}</strong> · {item.company}{item.expired && <em> 마감된 공고</em>}</span><button onClick={() => setItems(items.filter((x) => x.id !== item.id))}>저장 해제</button></li>)}</ul>}</main>;
}
