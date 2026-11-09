import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';
import './JobExplorerPage.css';

type Role = { job_role_id: string; name: string; code: string };
type Page = { items: Role[]; next_cursor: string | null };
type Detail = Role & { description: string | null; required_skills: { skill: { skill_id: string; name: string }; required_level: number }[] };

export function JobExplorerPage() {
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState(false);
  const [detailAttempt, setDetailAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ limit: '20' });
    if (query) params.set('q', query);
    const cursor = cursors[cursors.length - 1];
    if (cursor) params.set('cursor', cursor);
    Promise.resolve(attempt).then(() => apiGet<Page>(`/v1/job-roles?${params}`)).then(
      data => { if (active) { setPage(data); setError(false); } },
      () => { if (active) setError(true); },
    );
    return () => { active = false; };
  }, [query, cursors, attempt]);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    Promise.resolve(detailAttempt).then(() => apiGet<Detail>(`/v1/job-roles/${encodeURIComponent(selected)}`)).then(
      data => { if (active) { setDetail(data); setDetailError(false); } },
      () => { if (active) setDetailError(true); },
    );
    return () => { active = false; };
  }, [selected, detailAttempt]);

  function search(event: React.FormEvent) {
    event.preventDefault(); setPage(null); setError(false); setSelected(null); setDetail(null);
    setCursors([null]); setQuery(input.trim());
  }
  function select(id: string) { if (id === selected) return; setDetail(null); setDetailError(false); setSelected(id); }
  function changePage(next: (string | null)[]) { setPage(null); setError(false); setSelected(null); setDetail(null); setCursors(next); }

  return <div className="role-explorer">
    <header className="role-explorer-hero"><div><h1>직무 탐색</h1><p>직무와 필요한 기술을 살펴보세요.</p></div></header>
    <form className="role-explorer-controls" onSubmit={search}>
      <label htmlFor="role-query">직무 이름 검색</label>{' '}
      <input id="role-query" type="search" maxLength={100} value={input} onChange={e => setInput(e.target.value)} />{' '}
      <button type="submit">검색</button>
    </form>
    <div className="role-explorer-grid">
      <section className="role-explorer-panel" aria-labelledby="role-list-title"><h2 id="role-list-title">직무 목록</h2>
        {error ? <p role="alert">직무 목록을 불러오지 못했습니다. <button onClick={() => { setError(false); setAttempt(n => n + 1); }}>다시 시도</button></p>
          : !page ? <p role="status">불러오는 중...</p> : <>
            {page.items.length === 0 ? <p>검색 결과가 없습니다.</p> : <ul>{page.items.map(role => <li key={role.job_role_id}><button aria-pressed={selected === role.job_role_id} onClick={() => select(role.job_role_id)}>{role.name}</button></li>)}</ul>}
            <button disabled={cursors.length === 1} onClick={() => changePage(cursors.slice(0, -1))}>이전</button>{' '}
            <span>{cursors.length} 페이지</span>{' '}
            <button disabled={!page.next_cursor} onClick={() => page.next_cursor && changePage([...cursors, page.next_cursor])}>다음</button>
          </>}
      </section>
      <section className="role-explorer-panel" aria-labelledby="role-detail-title"><h2 id="role-detail-title">직무 상세</h2>
        {!selected ? <p>직무를 선택해 주세요.</p> : detailError ? <p role="alert">상세 정보를 불러오지 못했습니다. <button onClick={() => { setDetailError(false); setDetailAttempt(n => n + 1); }}>다시 시도</button></p>
          : !detail ? <p role="status">불러오는 중...</p> : <><h3>{detail.name}</h3><p>{detail.description || '설명이 없습니다.'}</p><h4>요구 기술</h4>{detail.required_skills.length ? <ul>{detail.required_skills.map(({ skill, required_level }) => <li key={skill.skill_id}>{skill.name} · 요구 수준 {required_level}</li>)}</ul> : <p>등록된 요구 기술이 없습니다.</p>}</>}
      </section>
    </div>
  </div>;
}
