import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';
import './JobPostingsPage.css';
import { CollectedJobsPreview } from './CollectedJobsPreview';

type Posting = { job_posting_id: string; title: string; status: 'published' | 'closed'; company: { name: string }; job_role: { name: string } | null; location_text: string | null; published_at: string | null; expires_at: string | null };
type Page = { items: Posting[]; next_cursor: string | null };
type Company = { company_id: string; name: string };
type Role = { job_role_id: string; name: string };
type Options<T> = { items: T[]; next_cursor: string | null };
type Detail = Posting & { description: string | null; source_url: string | null; required_skills: { skill: { skill_id: string; name: string }; required_level: number | null; is_required: boolean }[] };

function safeUrl(value: string | null) {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}

export function JobPostingsPage() {
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [companyQuery, setCompanyQuery] = useState('');
  const [roleQuery, setRoleQuery] = useState('');
  const [companyId, setCompanyId] = useState('');
  const [roleId, setRoleId] = useState('');
  const [companies, setCompanies] = useState<Options<Company> | null>(null);
  const [roles, setRoles] = useState<Options<Role> | null>(null);
  const [companyError, setCompanyError] = useState(false);
  const [roleError, setRoleError] = useState(false);
  const [optionsAttempt, setOptionsAttempt] = useState(0);
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
    void attempt; // Retry is an explicit request trigger.
    const params = new URLSearchParams({ limit: '20', sort, include_closed: String(includeClosed) });
    if (query) params.set('q', query);
    if (companyId) params.set('company_id', companyId);
    if (roleId) params.set('job_role_id', roleId);
    const cursor = cursors[cursors.length - 1];
    if (cursor) params.set('cursor', cursor);
    apiGet<Page>(`/v1/job-postings?${params}`).then(
      data => { if (active) { setPage(data); setError(false); } },
      () => { if (active) setError(true); },
    );
    return () => { active = false; };
  }, [query, sort, includeClosed, companyId, roleId, cursors, attempt]);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ limit: '20' });
    if (companyQuery.trim()) params.set('q', companyQuery.trim());
    void optionsAttempt; // Retry is an explicit request trigger.
    apiGet<Options<Company>>(`/v1/companies?${params}`).then(
      data => { if (active) setCompanies(data); },
      () => { if (active) setCompanyError(true); },
    );
    return () => { active = false; };
  }, [companyQuery, optionsAttempt]);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ limit: '20' });
    if (roleQuery.trim()) params.set('q', roleQuery.trim());
    void optionsAttempt; // Retry is an explicit request trigger.
    apiGet<Options<Role>>(`/v1/job-roles?${params}`).then(
      data => { if (active) setRoles(data); },
      () => { if (active) setRoleError(true); },
    );
    return () => { active = false; };
  }, [roleQuery, optionsAttempt]);
  useEffect(() => {
    if (!selected) return;
    void detailAttempt; // Retry is an explicit request trigger.
    let active = true;
    apiGet<Detail>(`/v1/job-postings/${encodeURIComponent(selected)}`).then(
      data => { if (active) { setDetail(data); setDetailError(false); } },
      () => { if (active) setDetailError(true); },
    );
    return () => { active = false; };
  }, [selected, detailAttempt]);
  function resetPage() { setPage(null); setError(false); setSelected(null); setDetail(null); setCursors([null]); }
  function retryOptions() { setCompanies(null); setRoles(null); setCompanyError(false); setRoleError(false); setOptionsAttempt(n => n + 1); }
  function search(event: React.FormEvent) { event.preventDefault(); resetPage(); setQuery(input.trim()); }
  function changePage(next: (string | null)[]) { setPage(null); setError(false); setSelected(null); setDetail(null); setCursors(next); }
  const source = detail ? safeUrl(detail.source_url) : null;

  return <div className="t24-page">
    <header className="t24-hero"><div><h1>채용공고 탐색</h1><p>등록된 채용공고와 요구 기술을 살펴보세요.</p></div><div className="t24-hero-symbol" aria-hidden="true">↗</div></header>
    {import.meta.env.DEV && import.meta.env.VITE_T24_COLLECTED_PREVIEW === 'true' && <CollectedJobsPreview />}
    <form className="t24-controls" onSubmit={search}>
      <label htmlFor="posting-query">공고 검색</label>{' '}<input id="posting-query" type="search" maxLength={100} value={input} onChange={e => setInput(e.target.value)} />{' '}<button type="submit">검색</button>{' '}
      <label htmlFor="company-search">기업 이름 찾기</label><input id="company-search" type="search" maxLength={100} value={companyQuery} onChange={e => { setCompanyQuery(e.target.value); setCompanies(null); setCompanyError(false); setCompanyId(''); resetPage(); }} />
      <label htmlFor="company-filter">기업 필터</label><select id="company-filter" value={companyId} disabled={!companies} onChange={e => { resetPage(); setCompanyId(e.target.value); }}><option value="">전체 기업</option>{companies?.items.map(company => <option key={company.company_id} value={company.company_id}>{company.name}</option>)}</select>
      {companyError && <p role="alert">기업 목록을 불러오지 못했습니다. <button type="button" onClick={retryOptions}>목록 다시 불러오기</button></p>}{companies?.next_cursor && <small>기업 이름을 입력해 검색 범위를 좁혀 주세요.</small>}
      <label htmlFor="role-search">직무 이름 찾기</label><input id="role-search" type="search" maxLength={100} value={roleQuery} onChange={e => { setRoleQuery(e.target.value); setRoles(null); setRoleError(false); setRoleId(''); resetPage(); }} />
      <label htmlFor="role-filter">직무 필터</label><select id="role-filter" value={roleId} disabled={!roles} onChange={e => { resetPage(); setRoleId(e.target.value); }}><option value="">전체 직무</option>{roles?.items.map(role => <option key={role.job_role_id} value={role.job_role_id}>{role.name}</option>)}</select>
      {roleError && <p role="alert">직무 목록을 불러오지 못했습니다. <button type="button" onClick={retryOptions}>목록 다시 불러오기</button></p>}{roles?.next_cursor && <small>직무 이름을 입력해 검색 범위를 좁혀 주세요.</small>}
      <label><input type="checkbox" checked={includeClosed} onChange={e => { resetPage(); setIncludeClosed(e.target.checked); }} /> 마감 공고 포함</label>{' '}
      <label>정렬 <select value={sort} onChange={e => { resetPage(); setSort(e.target.value as '-published_at' | 'expires_at'); }}><option value="-published_at">최신순</option><option value="expires_at">마감순</option></select></label>
    </form>
    <div className="t24-grid"><section className="t24-panel" aria-labelledby="posting-list-title"><h2 id="posting-list-title">정식 API 공고 목록</h2>
      {error ? <p role="alert">공고를 불러오지 못했습니다. <button onClick={() => { setError(false); setAttempt(n => n + 1); }}>다시 시도</button></p> : !page ? <p role="status">불러오는 중...</p> : <>
        {page.items.length === 0 ? <p>검색 결과가 없습니다.</p> : <ul className="t24-posting-list">{page.items.map(item => <li key={item.job_posting_id}><button className="t24-posting" aria-pressed={selected === item.job_posting_id} onClick={() => { if (selected === item.job_posting_id) return; setDetail(null); setDetailError(false); setSelected(item.job_posting_id); }}><strong>{item.title} · {item.company.name}</strong><span className="t24-status">{item.status === 'closed' ? '마감' : '모집 중'}</span></button></li>)}</ul>}
        <button disabled={cursors.length === 1} onClick={() => changePage(cursors.slice(0, -1))}>이전</button>{' '}<span>{cursors.length} 페이지</span>{' '}<button disabled={!page.next_cursor} onClick={() => page.next_cursor && changePage([...cursors, page.next_cursor])}>다음</button>
      </>}
    </section>
    <section className="t24-panel" aria-labelledby="posting-detail-title"><h2 id="posting-detail-title">공고 상세</h2>
      {!selected ? <p>공고를 선택해 주세요.</p> : detailError ? <p role="alert">상세 정보를 불러오지 못했습니다. <button onClick={() => { setDetailError(false); setDetailAttempt(n => n + 1); }}>다시 시도</button></p> : !detail ? <p role="status">불러오는 중...</p> : <>
        <h3>{detail.title}</h3><p>{detail.company.name} · {detail.job_role?.name ?? '직무 미등록'} · {detail.location_text ?? '지역 미등록'}</p><p>등록일: {detail.published_at ? new Date(detail.published_at).toLocaleDateString('ko-KR') : '미등록'} · 마감일: {detail.expires_at ? new Date(detail.expires_at).toLocaleDateString('ko-KR') : '미등록'}</p><p>{detail.description || '상세 설명이 없습니다.'}</p><h4>요구 기술</h4>
        {detail.required_skills.length ? <ul>{detail.required_skills.map(({ skill, required_level, is_required }) => <li key={skill.skill_id}>{skill.name} · {is_required ? '필수' : '우대'}{required_level != null ? ` · 요구 수준 ${required_level}` : ''}</li>)}</ul> : <p>등록된 요구 기술이 없습니다.</p>}
        {source && <a href={source} target="_blank" rel="noopener noreferrer">원본 공고 보기</a>}
      </>}
    </section></div>
  </div>;
}
