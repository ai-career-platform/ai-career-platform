import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Button } from '../components/Button';
import { FilterChips } from '../components/FilterChips';
import { StatePanel } from '../components/StatePanel';
import { TextField } from '../components/TextField';
import {
  DEMO_REFERENCE_DATE, filterDemoPostings, isClosed, loadMockPostings, pageDemoPostings,
  type DemoPosting, type PostingFilterStatus, type PostingSort,
} from './jobPostingData';
import './JobPostingsPage.css';

type Props = { loadPostings?: () => Promise<readonly DemoPosting[]> };
const statusOptions = [
  { value: 'open', label: '모집 중' },
  { value: 'closed', label: '마감' },
  { value: 'all', label: '전체' },
];

export function JobPostingsPage({ loadPostings = loadMockPostings }: Props) {
  const [params, setParams] = useSearchParams();
  const [postings, setPostings] = useState<readonly DemoPosting[]>([]);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [attempt, setAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.resolve(attempt).then(() => loadPostings()).then(
      (data) => {
        if (!active) return;
        if (!Array.isArray(data)) { setLoadState('error'); return; }
        setPostings(data);
        setLoadState('ready');
      },
      () => { if (active) setLoadState('error'); },
    );
    return () => { active = false; };
  }, [attempt, loadPostings]);

  const query = (params.get('q') ?? '').slice(0, 100);
  const companyId = params.get('company') ?? '';
  const role = params.get('role') ?? '';
  const statusValue = params.get('status');
  const status: PostingFilterStatus = statusValue === 'closed' || statusValue === 'all'
    ? statusValue : 'open';
  const order: PostingSort = params.get('order') === 'deadline' ? 'deadline' : 'recent';
  const pageValue = params.get('page') ?? '1';
  const requestedPage = /^[1-9][0-9]{0,4}$/.test(pageValue) ? Number(pageValue) : 1;

  const visible = useMemo(() => postings.filter((item) => item.status !== 'draft'), [postings]);
  const companies = useMemo(() =>
    [...new Map(visible.map((item) => [
      item.companyId, { id: item.companyId, name: item.companyName,
        description: item.companyDescription },
    ] as const)).values()].sort((a, b) => a.name.localeCompare(b.name, 'ko')), [visible]);
  const roles = useMemo(() =>
    [...new Set(visible.map((item) => item.role))].sort((a, b) => a.localeCompare(b, 'ko')), [visible]);

  const filtered = useMemo(() => filterDemoPostings(postings, {
    query, companyId, role, status, order, asOf: DEMO_REFERENCE_DATE,
  }), [postings, query, companyId, role, status, order]);
  const paginated = pageDemoPostings(filtered, requestedPage);
  const selected = filtered.find((item) => item.id === selectedId) ?? null;
  const selectedCompany = companies.find((item) => item.id === companyId);

  function changeFilter(key: 'q' | 'company' | 'role' | 'status' | 'order', value: string) {
    const next = new URLSearchParams(params);
    if (!value || (key === 'status' && value === 'open') ||
      (key === 'order' && value === 'recent')) next.delete(key);
    else next.set(key, value);
    next.delete('page');
    setParams(next, { replace: true });
    setSelectedId(null);
  }

  function changePage(nextPage: number) {
    const next = new URLSearchParams(params);
    if (nextPage === 1) next.delete('page');
    else next.set('page', String(nextPage));
    setParams(next);
    setSelectedId(null);
  }

  function reset() {
    setParams(new URLSearchParams(), { replace: true });
    setSelectedId(null);
  }

  function retry() {
    setLoadState('loading');
    setAttempt((value) => value + 1);
  }

  return (
    <div className="t24-page">
      <header className="t24-hero">
        <div>
          <p className="t24-eyebrow">FIND YOUR OPPORTUNITY</p>
          <h1>새로운 기회를 찾아보세요</h1>
          <p>관심 기업과 채용공고를 살펴보고, 직무별 요구 기술을 확인하세요.</p>
        </div>
        <span className="t24-hero-symbol" aria-hidden="true">✦</span>
      </header>
      <p className="t24-demo" role="note">
        <strong>UI 시안 · 합성 채용 데이터</strong>
        <span>기준일: {DEMO_REFERENCE_DATE}. 실제 모집 정보·마감일·기업 정보가 아니며 외부 지원 링크도 제공하지 않습니다.</span>
      </p>

      <section className="t24-companies" aria-labelledby="t24-company-heading">
        <div className="t24-section-heading">
          <h2 id="t24-company-heading">기업 둘러보기</h2>
          <span>가상 기업만 표시</span>
        </div>
        {loadState === 'ready' && (
          <div className="t24-company-list">
            {companies.map((company) => (
              <button key={company.id} type="button" className="t24-company"
                aria-pressed={company.id === companyId}
                onClick={() => changeFilter('company', company.id === companyId ? '' : company.id)}>
                <span aria-hidden="true" className="t24-company-avatar">{company.name.slice(0, 1)}</span>
                <span><strong>{company.name}</strong><small>가상 기업 · 공고 보기</small></span>
                <span className="t24-company-arrow" aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="t24-controls" aria-label="채용공고 검색 조건">
        <div className="t24-fields">
          <TextField label="채용공고·기업·기술 검색" type="search"
            maxLength={100} placeholder="예: 개발자, Python, 노바랩"
            value={query} onChange={(event) => changeFilter('q', event.target.value)} />
          <div className="t24-select">
            <label htmlFor="t24-company-filter">기업</label>
            <select id="t24-company-filter" value={companyId}
              onChange={(event) => changeFilter('company', event.target.value)}>
              <option value="">전체 기업</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>{company.name}</option>
              ))}
            </select>
          </div>
          <div className="t24-select">
            <label htmlFor="t24-role-filter">직무</label>
            <select id="t24-role-filter" value={role}
              onChange={(event) => changeFilter('role', event.target.value)}>
              <option value="">전체 직무</option>
              {roles.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
          <div className="t24-select">
            <label htmlFor="t24-order">정렬</label>
            <select id="t24-order" value={order}
              onChange={(event) => changeFilter('order', event.target.value)}>
              <option value="recent">최신순</option>
              <option value="deadline">마감 임박순</option>
            </select>
          </div>
        </div>
        <div className="t24-controls-bottom">
          <FilterChips label="공고 상태" options={statusOptions}
            value={status} onChange={(value) => changeFilter('status', value)} />
          <Button variant="outline" onClick={reset}>조건 초기화</Button>
        </div>
      </section>

      <div className="t24-grid">
        <section className="t24-panel" aria-labelledby="t24-postings-heading">
          <div className="t24-section-heading">
            <h2 id="t24-postings-heading">채용공고</h2>
            {loadState === 'ready' && <span role="status" aria-live="polite">
              검색 결과 {filtered.length}건</span>}
          </div>
          {loadState === 'loading' && <StatePanel variant="loading" title="예시 공고를 불러오는 중입니다" />}
          {loadState === 'error' && <StatePanel variant="error"
            title="채용공고를 불러오지 못했습니다"
            description="예시 데이터 로딩에 실패했습니다. 다시 시도해 주세요."
            actionLabel="다시 시도" onAction={retry} />}
          {loadState === 'ready' && filtered.length === 0 && <StatePanel
            variant="empty" title="조건에 맞는 공고가 없습니다"
            description="검색 조건이나 공고 상태를 변경해 보세요."
            actionLabel="검색 조건 초기화" onAction={reset} />}
          {loadState === 'ready' && filtered.length > 0 && (
            <>
              <ul className="t24-posting-list" aria-label="채용공고 검색 결과">
                {paginated.items.map((posting) => {
                  const closed = isClosed(posting, DEMO_REFERENCE_DATE);
                  return <li key={posting.id}>
                    <button type="button" className="t24-posting"
                      aria-label={posting.title + ' 상세 보기'}
                      aria-pressed={posting.id === selected?.id}
                      onClick={() => setSelectedId(posting.id)}>
                      <span className="t24-posting-top">
                        <span className={'t24-status ' + (closed ? 't24-status-closed' : '')}>
                          {closed ? '마감' : '모집 중'}
                        </span>
                        <span className="t24-posting-arrow" aria-hidden="true">↗</span>
                      </span>
                      <strong>{posting.title}</strong>
                      <span className="t24-posting-company">{posting.companyName} · {posting.role}</span>
                      <span className="t24-posting-meta">{posting.location} · {posting.employment} · {posting.expiresAt === null
                        ? '마감일 미정' : '마감 ' + posting.expiresAt.slice(0, 10)}</span>
                      <span className="t24-tags">
                        {posting.requiredSkills.slice(0, 3).map((skill) => (
                          <span key={skill}>{skill}</span>
                        ))}
                      </span>
                    </button>
                  </li>;
                })}
              </ul>
              <nav className="t24-pages" aria-label="공고 목록 페이지">
                <Button variant="outline" disabled={paginated.current === 1}
                  onClick={() => changePage(Math.max(1, paginated.current - 1))}>이전</Button>
                <span aria-live="polite">{paginated.current} / {paginated.pages} 페이지</span>
                <Button variant="outline" disabled={paginated.current === paginated.pages}
                  onClick={() => changePage(Math.min(paginated.pages, paginated.current + 1))}>다음</Button>
              </nav>
            </>
          )}
        </section>

        <section className="t24-panel t24-detail" aria-labelledby="t24-detail-heading">
          <div className="t24-section-heading">
            <h2 id="t24-detail-heading">공고 상세</h2>
            <span>JOB DETAILS</span>
          </div>
          {loadState !== 'ready' || selected === null ? (
            <div className="t24-detail-placeholder">
              <span aria-hidden="true">✦</span>
              <h3>공고를 선택해 주세요</h3>
              <p>목록에서 공고를 선택하면 기업 정보와 필요한 기술을 확인할 수 있어요.</p>
            </div>
          ) : <div className="t24-detail-content">
            <span className={'t24-status ' + (isClosed(selected, DEMO_REFERENCE_DATE) ? 't24-status-closed' : '')}>
              {isClosed(selected, DEMO_REFERENCE_DATE) ? '마감' : '모집 중'}
            </span>
            <h3>{selected.title}</h3>
            <p className="t24-detail-company">{selected.companyName} · {selected.role}</p>
            <p>{selected.description}</p>
            <dl className="t24-detail-facts">
              <div><dt>근무 지역</dt><dd>{selected.location}</dd></div>
              <div><dt>고용 형태</dt><dd>{selected.employment}</dd></div>
              <div><dt>게시일</dt><dd>{selected.publishedAt?.slice(0, 10) ?? '미정'}</dd></div>
              <div><dt>마감일</dt><dd>{selected.expiresAt?.slice(0, 10) ?? '미정'}</dd></div>
            </dl>
            <h4>요구 기술 <small>가상 예시</small></h4>
            <ul className="t24-detail-skills">
              {selected.requiredSkills.map((skill) => <li key={skill}>{skill}</li>)}
            </ul>
            <h4>기업 소개</h4>
            <p>{selected.companyDescription}</p>
            <div className="t24-source-note">
              <strong>출처: 합성 데이터 (synthetic_seed)</strong>
              <p>실제 원문·지원 링크가 없습니다. 출처 이용권과 URL 안전성을 검증하기 전에는 외부 사이트로 이동하지 않습니다.</p>
            </div>
          </div>}
          {selectedCompany && loadState === 'ready' && (
            <p className="t24-current-company" role="status">
              기업 필터: {selectedCompany.name}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
