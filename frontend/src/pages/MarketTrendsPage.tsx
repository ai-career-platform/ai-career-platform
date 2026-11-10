import { useId, useState } from 'react';
import { useApi } from '../api/ApiContext';
import { ApiError } from '../api/errors';
import { useQuery } from '../api/useQuery';
import type { MarketMetricCode, MarketPeriod, MarketTrend, MarketTrendQuery } from '../api/marketTrends';
import type { Skill } from '../api/catalog';
import { SEARCH_MIN_LENGTH } from '../api/skills';
import { DataTable } from '../components/DataTable';
import { FilterChips } from '../components/FilterChips';
import { MarketTrendChart } from '../components/MarketTrendChart';
import { StatePanel } from '../components/StatePanel';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import {
  MARKET_DISCLAIMER, METRIC_DEFINITIONS, METRIC_LABELS, PERIOD_LABELS, bucketsBetween, chartSegments, defaultRange, formatMetricValue,
  marketTrendErrorMessage, periodLabel, validateRange,
} from './marketTrendFormat';
import './MarketTrendsPage.css';


const metricOptions = (Object.keys(METRIC_LABELS) as MarketMetricCode[]).map((value) => ({ value, label: METRIC_LABELS[value] }));
const periodOptions = (Object.keys(PERIOD_LABELS) as MarketPeriod[]).map((value) => ({ value, label: `${PERIOD_LABELS[value]} 단위` }));
const unitLabels = { count: '건', ratio: '비율 (화면은 %)' } as const;

/** UI-024 채용시장 추세 대시보드 (F-024, FR-ANL-005). 로그인 필요 경로(RequireAuth) 아래에 둡니다. */
export function MarketTrendsPage() {
  const api = useApi();
  const ids = useId();
  const [metric, setMetric] = useState<MarketMetricCode>('posting_count');
  const [period, setPeriod] = useState<MarketPeriod>('week');
  const [range, setRange] = useState(defaultRange);
  const [roleId, setRoleId] = useState('');
  const [skill, setSkill] = useState<Skill | null>(null);
  const [skillQuery, setSkillQuery] = useState('');
  const debouncedSkillQuery = useDebouncedValue(skillQuery.trim(), 250);

  const roles = useQuery(['market-role-options'], (signal) => api.jobRoles.list({ limit: 100 }, signal));
  const needsSkill = metric === 'skill_demand_share';
  const skills = useQuery(needsSkill && debouncedSkillQuery.length >= SEARCH_MIN_LENGTH && ['market-skill-search', debouncedSkillQuery],
    (signal) => api.skills.search({ q: debouncedSkillQuery, limit: 20 }, signal));

  const rangeError = validateRange(range.from, range.to, period);
  const params: MarketTrendQuery = {
    metric_code: metric, from: range.from, to: range.to, period,
    job_role_id: roleId || null, skill_id: needsSkill ? skill?.skill_id ?? null : null,
  };
  const ready = !rangeError && (!needsSkill || skill !== null);
  // 조건이 바뀌면 이전 요청은 취소되고 늦게 온 이전 응답은 버려집니다(useQuery).
  const trend = useQuery(ready && ['market-trends', params], (signal) => api.marketTrends.get(params, signal));

  const roleOptions = roles.status === 'ready' ? roles.data.items : [];
  const skillOptions = skills.status === 'ready' ? skills.data.items : [];

  return (
    <section className="market-trends" aria-labelledby="market-trends-title">
      <header className="market-trends-heading">
        <h1 id="market-trends-title">채용시장 추세</h1>
        <p className="market-trends-intro">
          직무별 신규 공고 수와 기술 요구 비율의 관측값을 기간별로 확인합니다. 예측값은 이 화면에 표시하지 않습니다.
        </p>
        <p className="market-trends-disclaimer" role="note">{MARKET_DISCLAIMER}</p>
      </header>

      <form className="market-trends-filters" aria-label="조회 조건" onSubmit={(event) => event.preventDefault()}>
        <div className="market-trends-filter">
          <span className="market-trends-label">관측 지표</span>
          <FilterChips label="관측 지표" options={metricOptions} value={metric}
            onChange={(value) => setMetric(value as MarketMetricCode)} />
        </div>
        <div className="market-trends-filter">
          <span className="market-trends-label">집계 단위</span>
          <FilterChips label="집계 단위" options={periodOptions} value={period}
            onChange={(value) => setPeriod(value as MarketPeriod)} />
        </div>
        <div className="market-trends-row">
          <label className="market-trends-field">
            <span className="market-trends-label">시작일</span>
            <input type="date" value={range.from} max={range.to || undefined}
              aria-invalid={rangeError ? true : undefined} aria-describedby={rangeError ? `${ids}-range` : undefined}
              onChange={(event) => setRange((current) => ({ ...current, from: event.target.value }))} />
          </label>
          <label className="market-trends-field">
            <span className="market-trends-label">종료일</span>
            <input type="date" value={range.to} min={range.from || undefined}
              aria-invalid={rangeError ? true : undefined} aria-describedby={rangeError ? `${ids}-range` : undefined}
              onChange={(event) => setRange((current) => ({ ...current, to: event.target.value }))} />
          </label>
          <label className="market-trends-field">
            <span className="market-trends-label">직무</span>
            <select value={roleId} onChange={(event) => setRoleId(event.target.value)}
              aria-describedby={roles.status === 'error' ? `${ids}-roles` : undefined}>
              <option value="">전체 시장 (직무 구분 없음)</option>
              {roleOptions.map((role) => <option key={role.job_role_id} value={role.job_role_id}>{role.name}</option>)}
            </select>
          </label>
        </div>
        {roles.status === 'error' && (
          <p className="market-trends-note" id={`${ids}-roles`}>
            직무 목록을 불러오지 못해 전체 시장만 조회할 수 있습니다.{' '}
            <button type="button" className="market-trends-link" onClick={roles.retry}>직무 목록 다시 불러오기</button>
          </p>
        )}
        {needsSkill && (
          <div className="market-trends-row">
            <label className="market-trends-field">
              <span className="market-trends-label">기술 검색</span>
              <input type="search" value={skillQuery} placeholder="예: Python" autoComplete="off"
                onChange={(event) => setSkillQuery(event.target.value)} />
            </label>
            <label className="market-trends-field">
              <span className="market-trends-label">기술 (필수)</span>
              <select value={skill?.skill_id ?? ''} required
                onChange={(event) => setSkill(skillOptions.find((s) => s.skill_id === event.target.value) ?? skill)}>
                <option value="" disabled>{skills.status === 'loading' ? '검색 중…' : '기술을 검색해 선택하세요'}</option>
                {skill && !skillOptions.some((s) => s.skill_id === skill.skill_id) && (
                  <option value={skill.skill_id}>{skill.name}</option>
                )}
                {skillOptions.map((s) => <option key={s.skill_id} value={s.skill_id}>{s.name}</option>)}
              </select>
            </label>
          </div>
        )}
        {rangeError && <p className="market-trends-invalid" id={`${ids}-range`} role="alert">{rangeError}</p>}
      </form>

      <aside className="market-trends-definition" aria-label="지표 정의">
        <h2>지표 정의 · {METRIC_LABELS[metric]}</h2>
        <p>{METRIC_DEFINITIONS[metric]}</p>
        <p>관측이 없는 구간은 0이 아니라 빈 구간입니다. 그래프에서는 선을 끊고 표에는 행이 없습니다. 진행 중인 이번 주·이번 달은 집계하지 않습니다.</p>
      </aside>

      {!ready && !rangeError && needsSkill && (
        <StatePanel variant="empty" title="기술을 선택해 주세요" description="기술 요구 비율은 기술을 하나 선택해야 조회할 수 있습니다." />
      )}
      {trend.status === 'loading' && <StatePanel variant="loading" title="채용시장 추세를 불러오는 중입니다" />}
      {trend.status === 'error' && (
        <StatePanel
          variant="error"
          title="채용시장 추세를 불러오지 못했습니다"
          description={marketTrendErrorMessage(trend.error)}
          actionLabel={trend.error instanceof ApiError && trend.error.status === 401 ? undefined : '다시 시도'}
          onAction={trend.retry}
        />
      )}
      {trend.status === 'ready' && <TrendResult trend={trend.data} />}
    </section>
  );
}

function TrendResult({ trend }: { trend: MarketTrend }) {
  const { observations, unit, period, from, to } = trend;
  const scope = trend.job_role?.name ?? '전체 시장';
  const title = `${scope} ${trend.skill ? `${trend.skill.name} ` : ''}${METRIC_LABELS[trend.metric_code]} (${PERIOD_LABELS[period]} 단위)`;
  const placedCount = chartSegments(observations, bucketsBetween(from, to, period), period).flat().length;
  const last = observations.at(-1);

  return (
    <div className="market-trends-result">
      <dl className="market-trends-basis" aria-label="데이터 기준">
        <div><dt>출처</dt><dd>{trend.source ? `${trend.source.name} (${trend.source.code})` : '관측값 없음'}</dd></div>
        <div><dt>조회 기간</dt><dd>{from} ~ {to} · {PERIOD_LABELS[period]} 단위 (KST)</dd></div>
        <div><dt>범위</dt><dd>{scope}{trend.skill ? ` · ${trend.skill.name}` : ''}</dd></div>
        <div><dt>단위</dt><dd>{unitLabels[unit]}</dd></div>
        <div><dt>기준 시점 (마지막 관측 구간)</dt><dd>{last ? periodLabel(last.date, period) : '없음'}</dd></div>
      </dl>

      {observations.length === 0 ? (
        <StatePanel
          variant="empty"
          title="선택한 조건의 관측 데이터가 없습니다"
          description="관측값이 없는 것은 0건과 다릅니다. 기간·직무·지표를 바꿔 다시 조회해 주세요."
        />
      ) : (
        <>
          {placedCount !== observations.length && (
            <p className="market-trends-invalid" role="alert">
              관측값 {observations.length - placedCount}건을 그래프 구간에 놓지 못했습니다. 표의 값을 기준으로 확인해 주세요.
            </p>
          )}
          <MarketTrendChart title={title} observations={observations} period={period} from={from} to={to} unit={unit} />
          <DataTable
            caption={`${title} 관측값`}
            columns={[
              { key: 'period', header: '구간', render: (row) => periodLabel(row.date, period) },
              { key: 'value', header: METRIC_LABELS[trend.metric_code], render: (row) => formatMetricValue(row.value, unit) },
            ]}
            rows={observations}
            getRowKey={(row) => row.date}
          />
        </>
      )}
    </div>
  );
}
