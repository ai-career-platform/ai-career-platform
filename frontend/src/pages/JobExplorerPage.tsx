import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useApi } from '../api/ApiContext';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { StatePanel } from '../components/StatePanel';
import { TextField } from '../components/TextField';
import { MatchAction } from './MatchAction';
import { compareSkills, levelText } from './skillComparison';
import type { ComparisonStatus, UserSkillItem } from './skillComparison';
import './JobExplorerPage.css';

const PAGE_SIZE = 20;
const STATUS_LABEL: Record<ComparisonStatus, string> = {
  met: '충족', short: '부족', unrated: '숙련도 미입력', missing: '보유 기술에 없음',
};

/** 이 화면이 쓰는 직무 조회는 T17 카탈로그 API(`/v1/job-roles`)입니다. */
export function JobExplorerPage() {
  const [params, setParams] = useSearchParams();
  const query = (params.get('q') ?? '').trim().slice(0, 100);
  // 커서 목록은 검색어별로 따로 둡니다. 검색어가 바뀌면 첫 페이지부터 다시 시작합니다.
  const [cursorState, setCursorState] = useState<{ query: string; stack: (string | null)[] }>({ query, stack: [null] });
  // 검색어가 바뀌면 이전 검색어의 커서는 버립니다(같은 검색어로 돌아와도 1페이지부터).
  if (cursorState.query !== query) setCursorState({ query, stack: [null] });
  const stack = cursorState.query === query ? cursorState.stack : [null];
  const cursor = stack[stack.length - 1];
  const [selected, setSelected] = useState<string | null>(null);
  const auth = useAuth();
  const api = useApi();

  const list = useQuery(['job-roles', query, cursor], (signal) =>
    api.jobRoles.list({ limit: PAGE_SIZE, q: query, cursor }, signal));

  const detail = useQuery(selected !== null && ['job-role', selected], (signal) =>
    api.jobRoles.get(selected ?? '', signal));

  // 내 보유 기술은 로그인했을 때만 불러옵니다(T33 `GET /me/skills`, 인증 필요).
  const member = auth.state.status === 'authenticated' ? auth.state.user.email : null;
  const mySkills = useQuery<UserSkillItem[]>(member !== null && ['me-skills', member], (signal) =>
    api.me.skills.list(signal));

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get('q') ?? '').trim().slice(0, 100);
    setSelected(null);
    setParams(value ? { q: value } : {}, { replace: true });
  }
  function movePage(next: (string | null)[]) {
    setSelected(null);
    setCursorState({ query, stack: next });
  }

  const comparison = detail.status === 'ready' && mySkills.status === 'ready'
    ? compareSkills(detail.data.required_skills, mySkills.data) : null;
  const pageNumber = stack.length;

  return (
    <div className="role-explorer">
      <header className="role-explorer-hero">
        <div>
          <p className="role-explorer-eyebrow">EXPLORE YOUR PATH</p>
          <h1>어떤 일이 나와 맞을까요?</h1>
          <p>직무와 필요한 기술을 살펴보고, 로그인하면 내 보유 기술과 비교해 볼 수 있어요.</p>
        </div>
        <div className="role-explorer-hero-art" aria-hidden="true">↗</div>
      </header>
      <p className="role-explorer-notice" role="note">
        <strong>팀 직무 카탈로그 연동</strong>
        <span>직무와 요구 기술·수준은 카탈로그(T17 API) 값입니다. 보유 기술 비교는 숫자를 그대로 견준 단순 비교이며 AI Skill Gap 분석 결과가 아닙니다.</span>
      </p>

      <form className="role-explorer-controls" aria-label="직무 검색 조건" onSubmit={search} role="search">
        <div className="role-explorer-search-row">
          <TextField
            key={query} name="q" label="직무 이름 검색" type="search" maxLength={100}
            placeholder="예: 데이터 분석가, 백엔드" defaultValue={query}
            hint="현재 API는 직무 이름 검색만 지원합니다. 분야 필터·정렬·기술명으로 직무 찾기는 API가 제공되면 추가합니다."
          />
          <Button type="submit">검색</Button>
        </div>
      </form>

      <div className="role-explorer-grid">
        <section className="role-explorer-panel" aria-labelledby="t23-list-title">
          <div className="role-explorer-panel-heading">
            <h2 id="t23-list-title">직무 목록</h2>
            {list.status === 'ready' && (
              <span role="status" aria-live="polite" className="role-explorer-count">
                {query ? `“${query}” · ` : ''}{pageNumber}페이지 · {list.data.items.length}개 표시
              </span>
            )}
          </div>
          {list.status === 'loading' && <StatePanel variant="loading" title="직무를 불러오는 중입니다" />}
          {list.status === 'error' && (
            <StatePanel variant="error" title="직무 목록을 불러오지 못했습니다"
              description="네트워크 또는 서버 상태를 확인한 뒤 다시 시도해 주세요."
              actionLabel="다시 시도" onAction={list.retry} />
          )}
          {list.status === 'ready' && list.data.items.length === 0 && (
            <StatePanel variant="empty" title="검색 결과가 없습니다"
              description="직무 이름을 바꿔 다시 검색해 보세요."
              actionLabel={query ? '검색 조건 초기화' : undefined}
              onAction={query ? () => { setSelected(null); setParams({}, { replace: true }); } : undefined} />
          )}
          {list.status === 'ready' && list.data.items.length > 0 && (
            <>
              <ul className="role-explorer-results" aria-label="직무 검색 결과">
                {list.data.items.map((role) => (
                  <li key={role.job_role_id}>
                    <button type="button" className="role-explorer-card"
                      aria-pressed={selected === role.job_role_id}
                      aria-label={`${role.name} 상세 보기`}
                      onClick={() => setSelected(role.job_role_id)}>
                      <span className="role-explorer-card-top">
                        <span className="role-explorer-category">{role.code}</span>
                        <span aria-hidden="true">↗</span>
                      </span>
                      <strong className="role-explorer-card-title">{role.name}</strong>
                      <span className="role-explorer-description">선택하면 소개와 요구 기술을 볼 수 있어요.</span>
                    </button>
                  </li>
                ))}
              </ul>
              <nav className="role-explorer-pagination" aria-label="직무 목록 페이지">
                <Button variant="outline" disabled={stack.length === 1}
                  onClick={() => movePage(stack.slice(0, -1))}>이전</Button>
                <span aria-live="polite">{pageNumber} 페이지</span>
                <Button variant="outline" disabled={!list.data.next_cursor}
                  onClick={() => list.data.next_cursor && movePage([...stack, list.data.next_cursor])}>다음</Button>
              </nav>
            </>
          )}
        </section>

        <section className="role-explorer-panel role-explorer-details" aria-labelledby="t23-detail-title">
          <div className="role-explorer-panel-heading">
            <h2 id="t23-detail-title">직무 상세</h2>
            <span className="role-explorer-subtitle">ROLE PROFILE</span>
          </div>
          {!selected && (
            <div className="role-explorer-no-selection">
              <span aria-hidden="true" className="role-explorer-empty-icon">✦</span>
              <h3>직무를 선택해 주세요</h3>
              <p>직무 카드를 선택하면 소개와 필요한 기술을 확인할 수 있어요.</p>
            </div>
          )}
          {selected && detail.status === 'loading' && <StatePanel variant="loading" title="상세 정보를 불러오는 중입니다" />}
          {selected && detail.status === 'error' && (
            <StatePanel variant="error" title="상세 정보를 불러오지 못했습니다"
              actionLabel="다시 시도" onAction={detail.retry} />
          )}
          {selected && detail.status === 'ready' && (
            <div className="role-explorer-profile">
              <span className="role-explorer-category">{detail.data.code}</span>
              <h3>{detail.data.name}</h3>
              <p>{detail.data.description || '카탈로그에 등록된 직무 설명이 없습니다.'}</p>

              <h4>요구 기술 <small>카탈로그 기준 · 1~5단계</small></h4>
              {detail.data.required_skills.length === 0
                ? <p>등록된 요구 기술이 없습니다.</p>
                : (
                  <ul className="role-explorer-skills">
                    {detail.data.required_skills.map(({ skill, required_level }) => (
                      <li key={skill.skill_id}>
                        <span>{skill.name}</span>
                        <span>요구 {levelText(required_level)}</span>
                      </li>
                    ))}
                  </ul>
                )}

              <h4>내 보유 기술과 비교 <small>단순 비교 · AI 분석 아님</small></h4>
              {auth.state.status === 'loading' && <p>로그인 상태를 확인하는 중입니다.</p>}
              {auth.state.status === 'anonymous' && (
                <p className="role-explorer-login-hint">
                  <Link to="/login">로그인</Link>하면 내 보유 기술과 이 직무의 요구 수준을 비교하고 적합도도 계산해 볼 수 있어요.
                </p>
              )}
              {auth.state.status === 'authenticated' && mySkills.status === 'loading' && <p role="status">내 보유 기술을 불러오는 중입니다.</p>}
              {auth.state.status === 'authenticated' && mySkills.status === 'error' && (
                <StatePanel variant="error" title="내 보유 기술을 불러오지 못했습니다"
                  actionLabel="다시 시도" onAction={mySkills.retry} />
              )}
              {comparison && detail.data.required_skills.length > 0 && (
                <>
                  <p role="status" className="role-explorer-compare-summary">
                    요구 기술 {comparison.rows.length}개 중 {comparison.metCount}개 충족
                  </p>
                  <ul className="role-explorer-skills role-explorer-compare" aria-label="내 보유 기술 비교 결과">
                    {comparison.rows.map((row) => (
                      <li key={row.skillId}>
                        <span>{row.name}</span>
                        <span>
                          요구 {row.requiredLevel}{row.myLevel !== null ? ` · 내 수준 ${row.myLevel}` : ''}
                        </span>
                        <span className={`role-explorer-badge role-explorer-badge--${row.status}`}>
                          {STATUS_LABEL[row.status]}{row.gap ? ` (${row.gap}단계)` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {mySkills.status === 'ready' && mySkills.data.length === 0 && (
                    <p>아직 등록한 보유 기술이 없습니다. 보유 기술을 등록하면 비교 결과가 달라져요.</p>
                  )}
                </>
              )}
              <MatchAction target={{ job_role_id: detail.data.job_role_id }} targetName={detail.data.name} loginHint={false} />
              <p className="role-explorer-disclaimer">
                숙련도를 입력하지 않은 기술은 0으로 계산하지 않고 “숙련도 미입력”으로 따로 표시합니다. AI 기반 Skill Gap 분석(T26)·추천(T27)은 이 화면에 연결되어 있지 않습니다. “내 적합도 계산”은 T41 규칙 기반 점수이며 결과 화면에서 근거를 볼 수 있습니다.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
