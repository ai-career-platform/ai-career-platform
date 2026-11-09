import { useId } from 'react';
import type { SkillGap, SkillGapItem } from '../api/skillGaps';
import { Button } from '../components/Button';
import { DataTable, type TableColumn } from '../components/DataTable';
import { StatePanel } from '../components/StatePanel';
import './SkillGapPage.css';

export type SkillGapPageState =
  | { state: 'loading' }
  | { state: 'empty' }
  | { state: 'error' }
  | { state: 'unauthorized' }
  | { state: 'ready'; result: SkillGap };

type SkillGapPageProps = {
  status: SkillGapPageState;
  onRetry?: () => void;
  onAnalyze?: () => void;
  analyzing?: boolean;
  analysisFailed?: boolean;
};

const columns: TableColumn<SkillGapItem>[] = [
  { key: 'skill', header: '기술', render: (item) => item.skill.name },
  { key: 'required_level', header: '요구 수준', render: (item) => `${item.required_level} / 5` },
  { key: 'observed_level', header: '내 숙련도', render: (item) => item.observed_level === 0 ? '0 / 5 (미입력 포함)' : `${item.observed_level} / 5` },
  { key: 'gap', header: '부족 수준', render: (item) => item.gap === 0 ? '충족' : `${item.gap}` },
];

/** Presentational boundary: the authenticated container will supply API state. */
export function SkillGapPage({ status, onRetry, onAnalyze, analyzing = false, analysisFailed = false }: SkillGapPageProps) {
  const titleId = useId();
  const result = status.state === 'ready' ? status.result : null;
  const items = result ? [...result.items].sort((a, b) => b.gap - a.gap || (a.skill.code < b.skill.code ? -1 : a.skill.code > b.skill.code ? 1 : 0) || (a.skill.skill_id < b.skill.skill_id ? -1 : a.skill.skill_id > b.skill.skill_id ? 1 : 0)) : [];
  const missing = items.filter((item) => item.gap > 0);

  return (
    <section className="skill-gap-page" aria-labelledby={titleId}>
      <h1 id={titleId}>직무별 기술 차이 분석</h1>
      <p>목표 직무의 요구 수준과 내가 입력한 숙련도를 비교합니다.</p>
      {status.state === 'loading' && <StatePanel variant="loading" title="분석 결과를 불러오는 중입니다" />}
      {status.state === 'error' && <StatePanel variant="error" title="분석 결과를 불러오지 못했습니다" description="잠시 후 다시 시도해 주세요." actionLabel={onRetry ? '다시 시도' : undefined} onAction={onRetry} />}
      {status.state === 'unauthorized' && <StatePanel variant="unauthorized" title="로그인이 필요합니다" description="본인의 분석 결과만 확인할 수 있습니다." />}
      {status.state === 'empty' && <>
        <StatePanel variant="empty" title="아직 분석 결과가 없습니다" description="내 기술과 목표 직무를 등록한 뒤 분석해 주세요." />
        <Button onClick={onAnalyze} disabled={!onAnalyze || analyzing}>{analyzing ? '분석 중…' : '분석하기'}</Button>
      </>}
      {result && <>
        <h2>{result.job_role.name}</h2>
        <dl className="skill-gap-metadata">
          <div><dt>분석 시각</dt><dd><time dateTime={result.evaluated_at}>{new Date(result.evaluated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} (한국 시간)</time></dd></div>
          <div><dt>계산 방식</dt><dd>규칙 기반 · {result.model_version.model_code} {result.model_version.version}</dd></div>
          <div><dt>부족 기술</dt><dd>{missing.length}개</dd></div>
        </dl>
        {result.is_stale && <p role="status" className="skill-gap-stale">이전 입력으로 분석한 결과입니다. 현재 기술과 목표 직무를 반영하려면 재분석해 주세요.</p>}
        <p>부족 수준은 ‘요구 수준 − 내 숙련도’이며, 음수는 0으로 표시합니다. 숙련도 0에는 미등록·미평가 기술이 포함될 수 있습니다.</p>
        <p>부족 수준이 큰 순서로 표시합니다. 같은 수준의 기술은 같은 우선순위이며, 학습 순서는 참고용입니다.</p>
        {items.length === 0 ? <StatePanel variant="empty" title="비교할 기술 항목이 없습니다" description="이 결과만으로 요구 기술을 모두 충족한다고 판단할 수 없습니다." /> : <>
          {missing.length === 0 && <p role="status">분석에 포함된 기술의 요구 수준을 모두 충족했습니다.</p>}
          <DataTable caption="목표 직무와 내 기술 비교" columns={columns} rows={items} getRowKey={(item) => item.skill.skill_id} />
        </>}
        <Button onClick={onAnalyze} disabled={!onAnalyze || analyzing}>{analyzing ? '재분석 중…' : '재분석'}</Button>
      </>}
      {(result || status.state === 'empty') && analyzing && <p role="status" aria-live="polite">새로운 분석 결과를 기다리고 있습니다.</p>}
      {(result || status.state === 'empty') && analysisFailed && <p role="alert">{result ? '재분석에 실패했습니다. 표시 중인 결과는 이전 결과입니다.' : '분석에 실패했습니다.'} 다시 시도해 주세요.</p>}
    </section>
  );
}
