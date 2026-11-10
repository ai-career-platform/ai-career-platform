import { useState, type FormEvent } from 'react';
import { useAdminAuditService } from '../../admin/adminAuditContext';
import {
  ACTION_CODE_PATTERN, AUDIT_PAGE_SIZE, adminAuditErrorMessage, type AuditEvent, type AuditQuery,
} from '../../api/adminAudit';
import { useQuery } from '../../api/useQuery';
import { Button } from '../../components/Button';
import { DataTable, type TableColumn } from '../../components/DataTable';
import { StatePanel } from '../../components/StatePanel';
import { actorLabel, formatKstDateTime, kstInputToIso, resourceLabel, toKstInput } from './adminAuditFormat';
import './AdminAudit.css';

const DAY = 86_400_000;
type Applied = Pick<AuditQuery, 'from' | 'to' | 'action_code'>;

const columns: TableColumn<AuditEvent>[] = [
  { key: 'time', header: '발생 시각', render: (e) => formatKstDateTime(e.occurred_at) },
  { key: 'action', header: '작업 코드', render: (e) => <span className="audit-mono">{e.action_code}</span> },
  { key: 'resource', header: '대상', render: (e) => <span className="audit-mono">{resourceLabel(e)}</span> },
  { key: 'actor', header: '작업자', render: (e) => <span className="audit-mono">{actorLabel(e)}</span> },
  { key: 'request', header: '요청 ID', render: (e) => <span className="audit-mono">{e.request_id ?? '—'}</span> },
];

/** UI-028 운영 감사 — 감사 기록 검색 (T85, Mock 전용). GET /api/v1/admin/audit-events 확정 계약 기준. */
export function AuditEventsPage({ now = () => new Date() }: { now?: () => Date }) {
  const service = useAdminAuditService();
  const [initial] = useState(() => {
    const end = now();
    return { from: toKstInput(new Date(end.getTime() - 7 * DAY)), to: toKstInput(new Date(end.getTime() + 60_000)) };
  });
  const [fromInput, setFromInput] = useState(initial.from);
  const [toInput, setToInput] = useState(initial.to);
  const [actionInput, setActionInput] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [applied, setApplied] = useState<Applied>({ from: kstInputToIso(initial.from)!, to: kstInputToIso(initial.to)! });
  // 이전 페이지 이동용 cursor 스택. 비어 있으면 첫 페이지. 조건이 바뀌면 항상 비웁니다(이전 cursor 는 서버가 400 으로 거부).
  const [cursors, setCursors] = useState<string[]>([]);
  const [run, setRun] = useState(0);
  const cursor = cursors.at(-1);

  const list = useQuery(['admin-audit-events', applied, cursor ?? null, run],
    (signal) => service.listEvents({ ...applied, limit: AUDIT_PAGE_SIZE, cursor }, signal));

  function restart(next: Applied = applied) {
    setApplied(next);
    setCursors([]);
    setRun((n) => n + 1);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const from = kstInputToIso(fromInput);
    const to = kstInputToIso(toInput);
    const action = actionInput.trim();
    if (!from || !to) return setFormError('시작·종료 일시를 모두 입력해 주세요.');
    if (Date.parse(from) >= Date.parse(to)) return setFormError('시작 일시는 종료 일시보다 빨라야 합니다.');
    if (action && !ACTION_CODE_PATTERN.test(action)) {
      return setFormError('작업 코드는 영역.대상.동작 형식의 소문자입니다. 예: admin.role.grant');
    }
    setFormError(null);
    restart({ from, to, action_code: action || undefined });
  }

  const error = list.status === 'error' ? adminAuditErrorMessage(list.error) : null;
  const page = list.status === 'ready' ? list.data : null;

  return (
    <section className="audit-page" aria-labelledby="audit-title">
      <h1 id="audit-title">운영 감사 기록</h1>
      <div className="audit-notice" role="note">
        <p>가상 데이터(Mock) 화면입니다. 실제 감사 기록이 아니며, 서버 연결은 별도 승인 후입니다.</p>
        <p>페이지를 넘기는 동안 새로 기록되거나 늦게 저장된 기록은 빠지거나 나타날 수 있습니다(조회 시점 고정 아님). 최신 결과는 "새로 조회"로 다시 받으세요.</p>
        <p>사용자 ID로 찾기는 제공하지 않습니다. 조회 조건이 서버 접근 로그에 남을 수 있는 문제가 해결되지 않았기 때문입니다. 작업자 ID는 줄여서 표시합니다.</p>
      </div>

      <form className="audit-filters" onSubmit={submit} aria-label="감사 기록 검색 조건" noValidate>
        <label>시작 일시 (KST)
          <input type="datetime-local" value={fromInput} onChange={(e) => setFromInput(e.target.value)} required />
        </label>
        <label>종료 일시 (KST, 미포함)
          <input type="datetime-local" value={toInput} onChange={(e) => setToInput(e.target.value)} required />
        </label>
        <label>작업 코드
          <input value={actionInput} onChange={(e) => setActionInput(e.target.value)} maxLength={100}
            placeholder="예: admin.role.grant (비우면 전체)" />
        </label>
        <Button type="submit">조회</Button>
        <Button variant="outline" onClick={() => restart()}>새로 조회</Button>
      </form>
      {formError && <p className="audit-error" role="alert">{formError}</p>}

      {error ? (
        <StatePanel variant={error.forbidden ? 'unauthorized' : 'error'} title="감사 기록을 불러오지 못했습니다"
          description={error.message}
          actionLabel={error.resetCursor ? '처음부터 다시 조회' : error.retry ? '다시 시도' : undefined}
          onAction={error.resetCursor ? () => restart() : error.retry ? list.retry : undefined} />
      ) : page && page.items.length === 0 ? (
        <StatePanel variant="empty" title="조건에 맞는 감사 기록이 없습니다" description="기간이나 작업 코드를 바꿔 다시 조회해 주세요." />
      ) : (
        <DataTable caption="감사 기록 목록 (최신 순)" columns={columns} rows={page?.items ?? []}
          getRowKey={(e) => e.audit_event_id} loading={!page} />
      )}

      <nav className="audit-pager" aria-label="감사 기록 페이지">
        <Button variant="outline" disabled={cursors.length === 0}
          onClick={() => setCursors((stack) => stack.slice(0, -1))}>이전</Button>
        <span aria-live="polite">{cursors.length + 1}페이지</span>
        <Button variant="outline" disabled={!page?.next_cursor}
          onClick={() => page?.next_cursor && setCursors((stack) => [...stack, page.next_cursor!])}>다음</Button>
      </nav>
    </section>
  );
}
