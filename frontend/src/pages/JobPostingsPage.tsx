import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';
import './JobPostingsPage.css';

type Posting = { job_posting_id: string; title: string; status: 'published' | 'closed'; company: { name: string }; job_role: { name: string } | null; location_text: string | null; published_at: string | null; expires_at: string | null };
type Page = { items: Posting[]; next_cursor: string | null };
type Detail = Posting & { description: string | null; source_url: string | null; required_skills: { skill: { skill_id: string; name: string }; required_level: number | null; is_required: boolean }[] };

function safeUrl(value: string | null) {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}

export function JobPostingsPage() {
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [includeClosed, setIncludeClosed] = useState(false);
  const [sort, setSort] = useState<'-published_at' | 'expires_at'>('-published_at');
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
    const params = new URLSearchParams({ limit: '20', sort, include_closed: String(includeClosed) });
    if (query) params.set('q', query);
    const cursor = cursors[cursors.length - 1];
    if (cursor) params.set('cursor', cursor);
    apiGet<Page>(`/v1/job-postings?${params}`).then(
      data => { if (active) { setPage(data); setError(false); } },
      () => { if (active) setError(true); },
    );
    return () => { active = false; };
  }, [query, sort, includeClosed, cursors, attempt]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    apiGet<Detail>(`/v1/job-postings/${encodeURIComponent(selected)}`).then(
      data => { if (active) { setDetail(data); setDetailError(false); } },
      () => { if (active) setDetailError(true); },
    );
    return () => { active = false; };
  }, [selected, detailAttempt]);
  function resetPage() { setPage(null); setError(false); setSelected(null); setDetail(null); setCursors([null]); }
  function search(event: React.FormEvent) { event.preventDefault(); resetPage(); setQuery(input.trim()); }
  function changePage(next: (string | null)[]) { setPage(null); setError(false); setSelected(null); setDetail(null); setCursors(next); }
  const source = detail ? safeUrl(detail.source_url) : null;

  return <div className="t24-page">
    <header className="t24-hero"><div><h1>채용공고 탐색</h1><p>등록된 채용공고와 요구 기술을 살펴보세요.</p></div><div className="t24-hero-symbol" aria-hidden="true">↗</div></header>
    <form className="t24-controls" onSubmit={search}>
      <label htmlFor="posting-query">공고 검색</label>{' '}<input id="posting-query" type="search" maxLength={100} value={input} onChange={e => setInput(e.target.value)} />{' '}<button type="submit">검색</button>{' '}
      <label><input type="checkbox" checked={includeClosed} onChange={e => { resetPage(); setIncludeClosed(e.target.checked); }} /> 마감 공고 포함</label>{' '}
      <label>정렬 <select value={sort} onChange={e => { resetPage(); setSort(e.target.value as '-published_at' | 'expires_at'); }}><option value="-published_at">최신순</option><option value="expires_at">마감순</option></select></label>
    </form>
    <div className="t24-grid"><section className="t24-panel" aria-labelledby="posting-list-title"><h2 id="posting-list-title">공고 목록</h2>
      {error ? <p role="alert">공고를 불러오지 못했습니다. <button onClick={() => { setError(false); setAttempt(n => n + 1); }}>다시 시도</button></p> : !page ? <p role="status">불러오는 중...</p> : <>
        {page.items.length === 0 ? <p>검색 결과가 없습니다.</p> : <ul className="t24-posting-list">{page.items.map(item => <li key={item.job_posting_id}><button className="t24-posting" aria-pressed={selected === item.job_posting_id} onClick={() => { if (selected === item.job_posting_id) return; setDetail(null); setDetailError(false); setSelected(item.job_posting_id); }}><strong>{item.title} · {item.company.name}</strong><span className="t24-status">{item.status === 'closed' ? '마감' : '모집 중'}</span></button></li>)}</ul>}
        <button disabled={cursors.length === 1} onClick={() => changePage(cursors.slice(0, -1))}>이전</button>{' '}<span>{cursors.length} 페이지</span>{' '}<button disabled={!page.next_cursor} onClick={() => page.next_cursor && changePage([...cursors, page.next_cursor])}>다음</button>
      </>}
    </section>
    <section className="t24-panel" aria-labelledby="posting-detail-title"><h2 id="posting-detail-title">공고 상세</h2>
      {!selected ? <p>공고를 선택해 주세요.</p> : detailError ? <p role="alert">상세 정보를 불러오지 못했습니다. <button onClick={() => { setDetailError(false); setDetailAttempt(n => n + 1); }}>다시 시도</button></p> : !detail ? <p role="status">불러오는 중...</p> : <>
        <h3>{detail.title}</h3><p>{detail.company.name} · {detail.job_role?.name ?? '직무 미등록'} · {detail.location_text ?? '지역 미등록'}</p><p>{detail.description || '상세 설명이 없습니다.'}</p><h4>요구 기술</h4>
        {detail.required_skills.length ? <ul>{detail.required_skills.map(({ skill, required_level, is_required }) => <li key={skill.skill_id}>{skill.name} · {is_required ? '필수' : '우대'}{required_level != null ? ` · 요구 수준 ${required_level}` : ''}</li>)}</ul> : <p>등록된 요구 기술이 없습니다.</p>}
        {source && <a href={source} target="_blank" rel="noopener noreferrer">원본 공고 보기</a>}
      </>}
    </section></div>
  </div>;
}
