import { useEffect, useMemo, useState } from 'react';
import { Button } from '../components/Button';
import { FilterChips } from '../components/FilterChips';
import { StatePanel } from '../components/StatePanel';
import { TextField } from '../components/TextField';
import { filterJobRoles, loadMockJobRoles, pageJobRoles, type JobRole, type JobSort } from './jobExplorerData';
import './JobExplorerPage.css';

type Props = { loadRoles?: () => Promise<readonly JobRole[]> };

export function JobExplorerPage({ loadRoles = loadMockJobRoles }: Props) {
  const [roles, setRoles] = useState<readonly JobRole[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('전체');
  const [sort, setSort] = useState<JobSort>('name');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    // Use the attempt number as the explicit reload trigger.
    Promise.resolve(reload).then(() => loadRoles()).then(
      (data) => {
        if (!active) return;
        if (!Array.isArray(data)) { setState('error'); return; }
        setRoles(data);
        setState('ready');
      },
      () => { if (active) setState('error'); },
    );
    return () => { active = false; };
  }, [loadRoles, reload]);

  const options = useMemo(() =>
    ['전체', ...new Set(roles.map((role) => role.category))]
      .map((value) => ({ value, label: value })), [roles]);
  const filtered = useMemo(() =>
    filterJobRoles(roles, query, category, sort), [roles, query, category, sort]);
  const list = pageJobRoles(filtered, page);
  const selectedRole = filtered.find((role) => role.id === selected) ?? null;

  function reset() {
    setQuery(''); setCategory('전체'); setSort('name');
    setPage(1); setSelected(null);
  }
  function retry() {
    setState('loading');
    setReload((old) => old + 1);
  }

  return (
    <div className="role-explorer">
      <header className="role-explorer-hero">
        <div>
          <p className="role-explorer-eyebrow">EXPLORE YOUR PATH</p>
          <h1>어떤 일이 나와 맞을까요?</h1>
          <p>다양한 직무와 필요한 기술을 살펴보고 관심 분야를 찾아보세요.</p>
        </div>
        <div className="role-explorer-hero-art" aria-hidden="true">↗</div>
      </header>
      <p className="role-explorer-notice" role="note">
        <strong>UI 미리보기 · 가상 데이터</strong>
        <span>표시된 직무와 기술 수준은 합성 예제입니다. 실제 채용 정보나 AI 추천·개인 평가 결과가 아닙니다.</span>
      </p>

      <section className="role-explorer-controls" aria-label="직무 검색 조건">
        <div className="role-explorer-search-row">
          <TextField
            label="직무 또는 기술 검색" type="search" maxLength={100}
            placeholder="예: 데이터 분석가, Python" value={query}
            onChange={(event) => {
              setQuery(event.target.value); setPage(1); setSelected(null);
            }}
          />
          <div className="role-explorer-sort">
            <label htmlFor="t23-sort">정렬</label>
            <select id="t23-sort" value={sort}
              onChange={(event) => { setSort(event.target.value as JobSort); setPage(1); }}>
              <option value="name">이름순</option>
              <option value="category">분야순</option>
            </select>
          </div>
        </div>
        <FilterChips label="직무 분야" options={options} value={category}
          onChange={(value) => {
            setCategory(value); setPage(1); setSelected(null);
          }} />
      </section>

      <div className="role-explorer-grid">
        <section className="role-explorer-panel" aria-labelledby="t23-list-title">
          <div className="role-explorer-panel-heading">
            <h2 id="t23-list-title">직무 목록</h2>
            {state === 'ready' && (
              <span role="status" aria-live="polite" className="role-explorer-count">
                {filtered.length}개 직무
              </span>
            )}
          </div>
          {state === 'loading' && <StatePanel variant="loading" title="예시 직무를 불러오는 중입니다" />}
          {state === 'error' && (
            <StatePanel variant="error" title="직무 목록을 불러오지 못했습니다"
              description="예시 데이터 로딩에 실패했습니다. 다시 시도해 주세요."
              actionLabel="다시 시도" onAction={retry} />
          )}
          {state === 'ready' && filtered.length === 0 && (
            <StatePanel variant="empty" title="검색 결과가 없습니다"
              description="검색어나 분야를 바꿔 보세요."
              actionLabel="검색 조건 초기화" onAction={reset} />
          )}
          {state === 'ready' && filtered.length > 0 && (
            <>
              <ul className="role-explorer-results" aria-label="직무 검색 결과">
                {list.items.map((role) => (
                  <li key={role.id}>
                    <button type="button" className="role-explorer-card"
                      aria-pressed={selectedRole?.id === role.id}
                      aria-label={role.name + ' 상세 보기'}
                      onClick={() => setSelected(role.id)}>
                      <span className="role-explorer-card-top">
                        <span className="role-explorer-category">{role.category}</span>
                        <span aria-hidden="true">↗</span>
                      </span>
                      <strong className="role-explorer-card-title">{role.name}</strong>
                      <span className="role-explorer-description">{role.description}</span>
                      <span className="role-explorer-chips">
                        {role.skills.slice(0, 3).map((skill) => (
                          <span className="role-explorer-chip" key={skill.code}>{skill.name}</span>
                        ))}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <nav className="role-explorer-pagination" aria-label="직무 목록 페이지">
                <Button variant="outline" disabled={list.current === 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}>이전</Button>
                <span aria-live="polite">{list.current} / {list.pages} 페이지</span>
                <Button variant="outline" disabled={list.current === list.pages}
                  onClick={() => setPage((value) => Math.min(list.pages, value + 1))}>다음</Button>
              </nav>
            </>
          )}
        </section>

        <section className="role-explorer-panel role-explorer-details" aria-labelledby="t23-detail-title">
          <div className="role-explorer-panel-heading">
            <h2 id="t23-detail-title">직무 상세</h2>
            <span className="role-explorer-subtitle">ROLE PROFILE</span>
          </div>
          {state !== 'ready' || selectedRole === null ? (
            <div className="role-explorer-no-selection">
              <span aria-hidden="true" className="role-explorer-empty-icon">✦</span>
              <h3>직무를 선택해 주세요</h3>
              <p>직무 카드를 선택하면 소개와 필요한 기술을 확인할 수 있어요.</p>
            </div>
          ) : (
            <div className="role-explorer-profile">
              <span className="role-explorer-category">{selectedRole.category}</span>
              <h3>{selectedRole.name}</h3>
              <p>{selectedRole.description}</p>
              <h4>요구 기술 <small>가상 기준 · 1~5단계</small></h4>
              <ul className="role-explorer-skills">
                {selectedRole.skills.map((skill) => (
                  <li key={skill.code}>
                    <span>{skill.name}</span>
                    <span>예시 요구 수준 {skill.requiredLevel} / 5</span>
                  </li>
                ))}
              </ul>
              <p className="role-explorer-disclaimer">
                요구 수준은 화면 확인용 예시입니다. 실제 보유 기술·Skill Gap 분석은 연동되지 않았습니다.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
