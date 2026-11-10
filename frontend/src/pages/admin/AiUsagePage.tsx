import { useState, type FormEvent } from 'react';
import { useAdminAuditService } from '../../admin/adminAuditContext';
import {
  GROUP_BY_LABELS, adminAuditErrorMessage, type AiUsageBucket, type UsageGroupBy, type UsageQuery,
} from '../../api/adminAudit';
import { useQuery } from '../../api/useQuery';
import { Button } from '../../components/Button';
import { DataTable, type TableColumn } from '../../components/DataTable';
import { StatePanel } from '../../components/StatePanel';
import { formatInteger, formatUsd, kstDate, usageKeyLabel } from './adminAuditFormat';
import './AdminAudit.css';

const DAY = 86_400_000;
export const COST_WARNING = '추정 비용은 검증되지 않았으며 실제 청구액과 다를 수 있습니다.';
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** UI-028 AI 사용량·추정 비용 (T85, Mock 전용). GET /api/v1/admin/ai-usage 확정 계약 기준. */
export function AiUsagePage({ now = () => new Date() }: { now?: () => Date }) {
  const service = useAdminAuditService();
  const [initial] = useState(() => ({ from: kstDate(new Date(now().getTime() - 6 * DAY)), to: kstDate(now()) }));
  const [fromInput, setFromInput] = useState(initial.from);
  const [toInput, setToInput] = useState(initial.to);
  const [groupInput, setGroupInput] = useState<UsageGroupBy>('day');
  const [formError, setFormError] = useState<string | null>(null);
  const [applied, setApplied] = useState<UsageQuery>({ ...initial, group_by: 'day' });
  const [run, setRun] = useState(0);

  const usage = useQuery(['admin-ai-usage', applied, run], (signal) => service.getUsage(applied, signal));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!DATE.test(fromInput) || !DATE.test(toInput)) return setFormError('시작일과 종료일을 모두 입력해 주세요.');
    if (fromInput > toInput) return setFormError('시작일은 종료일보다 늦을 수 없습니다.');
    setFormError(null);
    setApplied({ from: fromInput, to: toInput, group_by: groupInput });
    setRun((n) => n + 1);
  }

  const groupBy = applied.group_by;
  const columns: TableColumn<AiUsageBucket>[] = [
    { key: 'key', header: GROUP_BY_LABELS[groupBy], render: (b) => <span className="audit-mono">{usageKeyLabel(groupBy, b.key)}</span> },
    { key: 'requests', header: '요청 수', render: (b) => <span className="audit-number">{formatInteger(b.request_count)}</span> },
    { key: 'input', header: '입력 토큰', render: (b) => <span className="audit-number">{formatInteger(b.input_tokens)}</span> },
    { key: 'output', header: '출력 토큰', render: (b) => <span className="audit-number">{formatInteger(b.output_tokens)}</span> },
    { key: 'cost', header: '추정 비용 (USD)', render: (b) => (
      <span className="audit-number">{formatUsd(b.estimated_cost_usd)}<span className="audit-badge">미검증</span>
        {b.estimated_cost_usd === 0 && <span className="audit-muted"> 무료로 확인된 값 아님</span>}
      </span>) },
  ];

  const error = usage.status === 'error' ? adminAuditErrorMessage(usage.error) : null;
  const result = usage.status === 'ready' ? usage.data : null;
  // 요청 수·토큰은 정수라 표의 합을 그대로 보여 줍니다. 비용 합계는 서버가 주지 않으므로 화면에서 계산하지 않습니다.
  const sum = (pick: (b: AiUsageBucket) => number) => (result ? result.buckets.reduce((acc, b) => acc + pick(b), 0) : 0);

  return (
    <section className="audit-page" aria-labelledby="usage-title">
      <h1 id="usage-title">AI 사용량·추정 비용</h1>
      <div className="audit-notice" role="note">
        <p>가상 데이터(Mock) 화면입니다. 표의 숫자는 합성 값이며 실제 사용량이나 비용이 발생했다는 뜻이 아닙니다.</p>
        <p>날짜는 한국 시간(KST) 기준이며 시작일·종료일을 모두 포함합니다. 최대 조회 기간은 아직 정해지지 않았습니다.</p>
      </div>
      <p className="audit-cost-warning" role="alert">{COST_WARNING}
        {result?.costStatus === 'unknown' && ' (서버가 비용 확인 상태를 알려 주지 않아 검증되지 않은 것으로 표시합니다.)'}
      </p>

      <form className="audit-filters" onSubmit={submit} aria-label="AI 사용량 조회 조건" noValidate>
        <label>시작일 (KST)<input type="date" value={fromInput} onChange={(e) => setFromInput(e.target.value)} required /></label>
        <label>종료일 (KST, 포함)<input type="date" value={toInput} onChange={(e) => setToInput(e.target.value)} required /></label>
        <label>집계 단위
          <select value={groupInput} onChange={(e) => setGroupInput(e.target.value as UsageGroupBy)}>
            {(Object.keys(GROUP_BY_LABELS) as UsageGroupBy[]).map((g) => <option key={g} value={g}>{GROUP_BY_LABELS[g]}</option>)}
          </select>
        </label>
        <Button type="submit">조회</Button>
      </form>
      {formError && <p className="audit-error" role="alert">{formError}</p>}

      {result?.source === 'mock' && <p className="audit-muted">표시 중: 가상 데이터(Mock)</p>}
      {error ? (
        <StatePanel variant={error.forbidden ? 'unauthorized' : 'error'} title="AI 사용량을 불러오지 못했습니다"
          description={error.message} actionLabel={error.retry ? '다시 시도' : undefined}
          onAction={error.retry ? usage.retry : undefined} />
      ) : result && result.buckets.length === 0 ? (
        <StatePanel variant="empty" title="집계된 사용 기록 없음" description="이 기간에 기록된 AI 사용량이 없습니다. 비용이 0원이라는 뜻은 아닙니다." />
      ) : (
        <>
          {result && (
            <dl className="audit-summary" aria-label="기간 합계">
              <div><dt>요청 수</dt><dd>{formatInteger(sum((b) => b.request_count))}</dd></div>
              <div><dt>입력 토큰</dt><dd>{formatInteger(sum((b) => b.input_tokens))}</dd></div>
              <div><dt>출력 토큰</dt><dd>{formatInteger(sum((b) => b.output_tokens))}</dd></div>
              <div><dt>추정 비용 합계</dt><dd className="audit-muted">서버 미제공 — 행별 값만 표시</dd></div>
            </dl>
          )}
          <DataTable caption={`AI 사용량 (${GROUP_BY_LABELS[groupBy]})`} columns={columns} rows={result?.buckets ?? []}
            getRowKey={(b) => b.key} loading={!result} />
        </>
      )}
    </section>
  );
}
