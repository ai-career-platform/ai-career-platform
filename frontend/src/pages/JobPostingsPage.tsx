import { useState } from 'react';
import type { FormEvent } from 'react';
import { useSearchParams } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useQuery } from '../api/useQuery';
import { Button } from '../components/Button';
import { FilterChips } from '../components/FilterChips';
import { StatePanel } from '../components/StatePanel';
import { TextField } from '../components/TextField';
import { employmentLabel, formatDate, safeExternalUrl, uuidOrEmpty } from './postingFormat';
import { PostingApplicationButton } from './PostingApplicationButton';
import { PostingBookmarkToggle } from './PostingBookmarkToggle';
import {
  EMPLOYMENT_TYPES, MAX_VALUES, POSTED_WITHIN, POSTED_WITHIN_LABELS, REGIONS,
  type EmploymentType, type JobSearchService, type PostedWithin, type RegionCode,
} from '../api/jobSearch';
import { createMockJobSearchService } from '../mocks/jobSearch';
import { EMPTY_STATE, hasAnyFilter, normalizeSearch, parseSearch, serializeSearch, toApiQuery, type SearchState } from './jobSearchUrl';
import './JobPostingsPage.css';

type Sort = '-published_at' | 'expires_at';

const PAGE_SIZE = 20;
const OPTION_LIMIT = 100; // API 최대치. 이보다 많으면 안내 문구를 보여 줍니다.
const COMPANY_PREVIEW = 8;
const STATUS_OPTIONS = [
  { value: 'open', label: '모집 중만' },
  { value: 'all', label: '마감 포함' },
];

/**
 * 이 화면이 쓰는 공고 조회는 T18 정식 API(`/v1/job-postings`, `/v1/companies`)입니다. 별도 수집 API 데이터는 섞지 않습니다.
 *
 * `advanced`(T100): T98 고급 검색 계약(PROPOSED)으로 고용형태·지역·게시 기간을 더합니다. 기능 플래그(Mock 전용)일 때만 켜지고,
 * 데이터는 Mock Adapter 입니다(서버 T99 는 기능 플래그 뒤, 기본 꺼짐). URL 쿼리 = API 쿼리 이름이며, 조건을 바꿀 때마다
 * 기록이 쌓여 브라우저 뒤로가기로 이전 조건으로 돌아갑니다. 꺼져 있으면 기존 T24 동작 그대로입니다.
 */
export function JobPostingsPage({ advanced = false, searchService }: { advanced?: boolean; searchService?: JobSearchService } = {}) {
  const api = useApi();
  const [params, setParams] = useSearchParams();
  const adv: SearchState | null = advanced ? parseSearch(params) : null;
  const query = adv ? adv.q : (params.get('q') ?? '').trim().slice(0, 100);
  const companyId = adv ? (adv.company_id[0] ?? '') : uuidOrEmpty(params.get('company'));
  const roleId = adv ? (adv.job_role_id[0] ?? '') : uuidOrEmpty(params.get('role'));
  const includeClosed = adv ? adv.include_closed : params.get('closed') === '1';
  const sort: Sort = adv ? adv.sort : params.get('order') === 'expires' ? 'expires_at' : '-published_at';
  const [fallbackSearch] = useState(() => (advanced && !searchService ? createMockJobSearchService({ latencyMs: 150 }) : null));
  const search = searchService ?? fallbackSearch;

  // 커서 목록은 검색 조건별로 따로 둡니다. 조건이 바뀌면 첫 페이지부터 다시 시작합니다.
  const filterKey = adv ? serializeSearch(adv).toString() : [query, companyId, roleId, includeClosed, sort].join('|');
  const [cursorState, setCursorState] = useState<{ key: string; stack: (string | null)[] }>({ key: filterKey, stack: [null] });
  // 조건이 바뀌면 이전 조건의 커서는 버립니다(같은 조건으로 돌아와도 1페이지부터).
  if (cursorState.key !== filterKey) setCursorState({ key: filterKey, stack: [null] });
  const stack = cursorState.key === filterKey ? cursorState.stack : [null];
  const cursor = stack[stack.length - 1];
  const [selected, setSelected] = useState<string | null>(null);
  const [showAllCompanies, setShowAllCompanies] = useState(false);

  const list = useQuery(['job-postings', advanced, filterKey, cursor], (signal) => (adv && search
    ? search.list(toApiQuery(adv, PAGE_SIZE, cursor ?? null), signal)
    : api.jobPostings.list(
      { limit: PAGE_SIZE, sort, include_closed: includeClosed, q: query, company_id: companyId, job_role_id: roleId, cursor },
      signal,
    )));

  const companies = useQuery(['company-options'], (signal) =>
    api.companies.list({ limit: OPTION_LIMIT }, signal));
  const roles = useQuery(['role-options'], (signal) =>
    api.jobRoles.list({ limit: OPTION_LIMIT }, signal));

  const detail = useQuery(selected !== null && ['job-posting', selected], (signal) =>
    api.jobPostings.get(selected ?? '', signal));

  const detailCompanyId = detail.status === 'ready' ? detail.data.company.company_id : null;
  const companyDetail = useQuery(detailCompanyId !== null && ['company', detailCompanyId], (signal) =>
    api.companies.get(detailCompanyId ?? '', signal));

  /** 고급 모드: 조건을 바꿀 때마다 기록을 남김(push) → 뒤로가기로 이전 조건 */
  function changeAdvanced(patch: Partial<SearchState>) {
    if (!adv) return;
    setSelected(null);
    setParams(serializeSearch(normalizeSearch({ ...adv, ...patch })));
  }
  function change(patch: Record<string, string>) {
    if (adv) {
      const map: Partial<SearchState> = {};
      if ('q' in patch) map.q = patch.q ?? '';
      if ('company' in patch) map.company_id = patch.company ? [patch.company] : [];
      if ('role' in patch) map.job_role_id = patch.role ? [patch.role] : [];
      if ('closed' in patch) map.include_closed = patch.closed === '1';
      if ('order' in patch) map.sort = patch.order === 'expires' ? 'expires_at' : '-published_at';
      changeAdvanced(map);
      return;
    }
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value); else next.delete(key);
    }
    setSelected(null);
    setParams(next, { replace: true });
  }
  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    change({ q: String(new FormData(event.currentTarget).get('q') ?? '').trim().slice(0, 100) });
  }
  function movePage(next: (string | null)[]) {
    setSelected(null);
    setCursorState({ key: filterKey, stack: next });
  }
  const hasFilters = adv ? hasAnyFilter(adv) : Boolean(query || companyId || roleId || includeClosed || sort !== '-published_at');
  // 고급 모드 초기화는 검색어·필터만 지우고 정렬은 유지(T98 §6)
  const reset = () => {
    setSelected(null);
    if (adv) setParams(serializeSearch({ ...EMPTY_STATE, sort: adv.sort }));
    else setParams({}, { replace: true });
  };
  const toggle = <T extends string>(values: T[], value: T) =>
    (values.includes(value) ? values.filter((v) => v !== value) : [...values, value]);

  const companyItems = companies.status === 'ready' ? companies.data.items : [];
  const visibleCompanies = showAllCompanies ? companyItems : companyItems.slice(0, COMPANY_PREVIEW);
  const selectedCompany = companyItems.find((item) => item.company_id === companyId);
  const source = detail.status === 'ready' ? safeExternalUrl(detail.data.source_url) : null;
  const pageNumber = stack.length;

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
        <strong>정식 공고 API(T18) 연동</strong>
        <span>정식 서비스 DB의 공고만 표시합니다. 모집 상태·마감일·요구 기술은 API 값 그대로이며 추정하지 않습니다. 별도 수집 데이터는 이 목록에 섞지 않습니다.</span>
      </p>

      <section className="t24-companies" aria-labelledby="t24-company-heading">
        <div className="t24-section-heading">
          <h2 id="t24-company-heading">기업 둘러보기</h2>
          {companies.status === 'ready' && <span>기업 {companyItems.length}곳{companies.data.next_cursor ? ' 이상' : ''}</span>}
        </div>
        {companies.status === 'loading' && <StatePanel variant="loading" title="기업을 불러오는 중입니다" />}
        {companies.status === 'error' && (
          <StatePanel variant="error" title="기업 목록을 불러오지 못했습니다"
            actionLabel="다시 시도" onAction={companies.retry} />
        )}
        {companies.status === 'ready' && companyItems.length === 0 && (
          <StatePanel variant="empty" title="등록된 기업이 없습니다" description="기업이 등록되면 이곳에 표시됩니다." />
        )}
        {companies.status === 'ready' && companyItems.length > 0 && (
          <>
            <div className="t24-company-list">
              {visibleCompanies.map((company) => (
                <button key={company.company_id} type="button" className="t24-company"
                  aria-pressed={company.company_id === companyId}
                  onClick={() => change({ company: company.company_id === companyId ? '' : company.company_id })}>
                  <span aria-hidden="true" className="t24-company-avatar">{company.name.slice(0, 1)}</span>
                  <span><strong>{company.name}</strong><small>공고 보기</small></span>
                  <span className="t24-company-arrow" aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
            {companyItems.length > COMPANY_PREVIEW && (
              <Button variant="outline" className="t24-more" onClick={() => setShowAllCompanies((value) => !value)}>
                {showAllCompanies ? '기업 목록 접기' : `기업 ${companyItems.length}곳 모두 보기`}
              </Button>
            )}
            {companies.data.next_cursor && <p className="t24-hint">기업이 더 있어 일부만 표시합니다. 공고 검색에 기업 이름을 입력해 보세요.</p>}
          </>
        )}
      </section>

      <form className="t24-controls" role="search" aria-label="채용공고 검색 조건" onSubmit={submitSearch}>
        <div className="t24-fields">
          <div className="t24-search">
            <TextField key={query} name="q" label={adv ? '공고·기업 검색' : '공고 검색'} type="search" maxLength={100}
              placeholder={adv ? '예: 백엔드, 기업 이름' : '예: 백엔드, 데이터'} defaultValue={query} />
            <Button type="submit">검색</Button>
          </div>
          <div className="t24-select">
            <label htmlFor="t24-company-filter">기업</label>
            <select id="t24-company-filter" value={companyId} disabled={companies.status !== 'ready'}
              onChange={(event) => change({ company: event.target.value })}>
              <option value="">전체 기업</option>
              {companyItems.map((item) => <option key={item.company_id} value={item.company_id}>{item.name}</option>)}
            </select>
          </div>
          <div className="t24-select">
            <label htmlFor="t24-role-filter">직무</label>
            <select id="t24-role-filter" value={roleId} disabled={roles.status !== 'ready'}
              onChange={(event) => change({ role: event.target.value })}>
              <option value="">전체 직무</option>
              {(roles.status === 'ready' ? roles.data.items : []).map((item) => (
                <option key={item.job_role_id} value={item.job_role_id}>{item.name}</option>
              ))}
            </select>
          </div>
          <div className="t24-select">
            <label htmlFor="t24-order">정렬</label>
            <select id="t24-order" value={sort === 'expires_at' ? 'expires' : ''}
              onChange={(event) => change({ order: event.target.value })}>
              <option value="">최신 등록순</option>
              <option value="expires">마감 임박순</option>
            </select>
          </div>
        </div>
        {adv && (
          <fieldset className="t100-advanced">
            <legend>상세 조건 <span className="t100-badge">시범 · Mock</span></legend>
            <div className="t100-group" role="group" aria-labelledby="t100-employment">
              <span id="t100-employment" className="t100-group-title">고용 형태</span>
              {EMPLOYMENT_TYPES.map((type: EmploymentType) => (
                <label key={type} className="t100-check">
                  <input type="checkbox" checked={adv.employment_type.includes(type)}
                    onChange={() => changeAdvanced({ employment_type: toggle(adv.employment_type, type) })} />
                  {employmentLabel(type)}
                </label>
              ))}
            </div>
            <details className="t100-regions" open={adv.region.length > 0}>
              <summary>근무 지역{adv.region.length ? ` (${adv.region.length}개 선택)` : ''}</summary>
              <p className="t24-hint" id="t100-region-hint">
                공고의 근무지 표기 첫 단어로 판단한 추정값입니다. 최대 {MAX_VALUES.region}개까지 고를 수 있습니다.
              </p>
              <div className="t100-group" role="group" aria-label="근무 지역" aria-describedby="t100-region-hint">
                {REGIONS.map(([code, label]) => {
                  const checked = adv.region.includes(code as RegionCode);
                  return (
                    <label key={code} className="t100-check">
                      <input type="checkbox" checked={checked}
                        disabled={!checked && adv.region.length >= MAX_VALUES.region}
                        onChange={() => changeAdvanced({ region: toggle(adv.region, code as RegionCode) })} />
                      {label}
                    </label>
                  );
                })}
              </div>
            </details>
            <div className="t24-select">
              <label htmlFor="t100-posted">게시일</label>
              <select id="t100-posted" value={adv.posted_within}
                onChange={(event) => changeAdvanced({ posted_within: event.target.value as PostedWithin | '' })}>
                <option value="">전체 기간</option>
                {POSTED_WITHIN.map((value) => <option key={value} value={value}>{POSTED_WITHIN_LABELS[value]}</option>)}
              </select>
            </div>
            <p className="t24-hint">검색어는 공고 제목과 기업 이름에서 찾습니다. 기술·경력·연봉 조건은 데이터가 없어 제공하지 않습니다.</p>
          </fieldset>
        )}
        {roles.status === 'error' && (
          <p role="alert" className="t24-hint">직무 목록을 불러오지 못했습니다. <button type="button" className="t24-link" onClick={roles.retry}>다시 시도</button></p>
        )}
        {roles.status === 'ready' && roles.data.next_cursor && <p className="t24-hint">직무가 많아 일부만 표시합니다.</p>}
        <div className="t24-controls-bottom">
          <FilterChips label="공고 상태" options={STATUS_OPTIONS} value={includeClosed ? 'all' : 'open'}
            onChange={(value) => change({ closed: value === 'all' ? '1' : '' })} />
          <Button variant="outline" onClick={reset} disabled={!hasFilters}>조건 초기화</Button>
        </div>
        <p className="t24-hint">마감 공고만 따로 보는 필터는 API가 지원하지 않아 “마감 포함”으로만 제공합니다.</p>
      </form>

      <div className="t24-grid">
        <section className="t24-panel" aria-labelledby="t24-postings-heading">
          <div className="t24-section-heading">
            <h2 id="t24-postings-heading">채용공고</h2>
            {list.status === 'ready' && (
              <span role="status" aria-live="polite">
                {pageNumber}페이지 · {list.data.items.length}건 표시{selectedCompany ? ` · ${selectedCompany.name}` : ''}
              </span>
            )}
          </div>
          {list.status === 'loading' && <StatePanel variant="loading" title="공고를 불러오는 중입니다" />}
          {list.status === 'error' && (
            <StatePanel variant="error" title="채용공고를 불러오지 못했습니다"
              description="네트워크 또는 서버 상태를 확인한 뒤 다시 시도해 주세요."
              actionLabel="다시 시도" onAction={list.retry} />
          )}
          {list.status === 'ready' && list.data.items.length === 0 && (
            <StatePanel variant="empty" title="조건에 맞는 공고가 없습니다"
              description="검색어나 기업·직무·공고 상태를 바꿔 보세요."
              actionLabel={hasFilters ? '검색 조건 초기화' : undefined} onAction={hasFilters ? reset : undefined} />
          )}
          {list.status === 'ready' && list.data.items.length > 0 && (
            <>
              <ul className="t24-posting-list" aria-label="채용공고 검색 결과">
                {list.data.items.map((posting) => (
                  <li key={posting.job_posting_id}>
                    <button type="button" className="t24-posting"
                      aria-label={`${posting.title} 상세 보기`}
                      aria-pressed={posting.job_posting_id === selected}
                      onClick={() => setSelected(posting.job_posting_id)}>
                      <span className="t24-posting-top">
                        <span className={`t24-status ${posting.status === 'closed' ? 't24-status-closed' : ''}`}>
                          {posting.status === 'closed' ? '마감' : '모집 중'}
                        </span>
                        <span className="t24-posting-arrow" aria-hidden="true">↗</span>
                      </span>
                      <strong>{posting.title}</strong>
                      <span className="t24-posting-company">{posting.company.name} · {posting.job_role?.name ?? '직무 미등록'}</span>
                      <span className="t24-posting-meta">
                        {posting.location_text ?? '지역 미등록'} · {employmentLabel(posting.employment_type)} · {posting.expires_at ? `마감 ${formatDate(posting.expires_at)}` : '마감일 미정'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <nav className="t24-pages" aria-label="공고 목록 페이지">
                <Button variant="outline" disabled={stack.length === 1}
                  onClick={() => movePage(stack.slice(0, -1))}>이전</Button>
                <span aria-live="polite">{pageNumber} 페이지</span>
                <Button variant="outline" disabled={!list.data.next_cursor}
                  onClick={() => list.data.next_cursor && movePage([...stack, list.data.next_cursor])}>다음</Button>
              </nav>
            </>
          )}
        </section>

        <section className="t24-panel t24-detail" aria-labelledby="t24-detail-heading">
          <div className="t24-section-heading">
            <h2 id="t24-detail-heading">공고 상세</h2>
            <span>JOB DETAILS</span>
          </div>
          {!selected && (
            <div className="t24-detail-placeholder">
              <span aria-hidden="true">✦</span>
              <h3>공고를 선택해 주세요</h3>
              <p>목록에서 공고를 선택하면 기업 정보와 필요한 기술을 확인할 수 있어요.</p>
            </div>
          )}
          {selected && detail.status === 'loading' && <StatePanel variant="loading" title="상세 정보를 불러오는 중입니다" />}
          {selected && detail.status === 'error' && (
            <StatePanel variant="error" title="상세 정보를 불러오지 못했습니다"
              actionLabel="다시 시도" onAction={detail.retry} />
          )}
          {selected && detail.status === 'ready' && (
            <div className="t24-detail-content">
              <span className={`t24-status ${detail.data.status === 'closed' ? 't24-status-closed' : ''}`}>
                {detail.data.status === 'closed' ? '마감' : '모집 중'}
              </span>
              <h3>{detail.data.title}</h3>
              <p className="t24-detail-company">{detail.data.company.name} · {detail.data.job_role?.name ?? '직무 미등록'}</p>
              <PostingBookmarkToggle key={`${detail.data.job_posting_id}:${String(detail.data.is_bookmarked)}`}
                postingId={detail.data.job_posting_id} initial={detail.data.is_bookmarked ?? null} />
              <PostingApplicationButton key={`app:${detail.data.job_posting_id}`} postingId={detail.data.job_posting_id} />
              <p>{detail.data.description || '등록된 상세 설명이 없습니다.'}</p>
              <dl className="t24-detail-facts">
                <div><dt>근무 지역</dt><dd>{detail.data.location_text ?? '미등록'}</dd></div>
                <div><dt>고용 형태</dt><dd>{employmentLabel(detail.data.employment_type)}</dd></div>
                <div><dt>게시일</dt><dd>{formatDate(detail.data.published_at)}</dd></div>
                <div><dt>마감일</dt><dd>{formatDate(detail.data.expires_at, '미정')}</dd></div>
              </dl>
              <h4>요구 기술</h4>
              {detail.data.required_skills.length === 0
                ? <p>등록된 요구 기술이 없습니다.</p>
                : (
                  <ul className="t24-detail-skills" aria-label="요구 기술">
                    {detail.data.required_skills.map(({ skill, required_level, is_required }) => (
                      <li key={skill.skill_id}>
                        {skill.name} · {is_required ? '필수' : '우대'} · {required_level !== null ? `요구 수준 ${required_level}/5` : '요구 수준 미등록'}
                      </li>
                    ))}
                  </ul>
                )}

              <h4>기업 소개</h4>
              {companyDetail.status === 'loading' && <p role="status">기업 정보를 불러오는 중입니다.</p>}
              {companyDetail.status === 'error' && (
                <StatePanel variant="error" title="기업 정보를 불러오지 못했습니다"
                  actionLabel="다시 시도" onAction={companyDetail.retry} />
              )}
              {companyDetail.status === 'ready' && (() => {
                const site = safeExternalUrl(companyDetail.data.website_url);
                return (
                  <>
                    <p>{companyDetail.data.description || '등록된 기업 소개가 없습니다.'}</p>
                    <p className="t24-company-meta">
                      진행 중 공고 {companyDetail.data.open_posting_count}건
                      {site && <> · <a href={site.href} target="_blank" rel="noopener noreferrer">{site.host} (외부 사이트)</a></>}
                    </p>
                  </>
                );
              })()}

              <div className="t24-source-note">
                <strong>
                  데이터 출처{companyDetail.status === 'ready' ? `: ${companyDetail.data.source}` : ''}
                  {companyDetail.status === 'ready' && companyDetail.data.source === 'synthetic_seed' ? ' (합성 테스트 데이터 · 실제 채용 정보 아님)' : ''}
                </strong>
                {source
                  ? <p>원문은 외부 사이트입니다. <a href={source.href} target="_blank" rel="noopener noreferrer">{source.host}에서 원문 보기</a> — 이동 전 출처의 이용 조건을 확인하세요.</p>
                  : <p>이 공고는 원문 링크가 제공되지 않았습니다.</p>}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
