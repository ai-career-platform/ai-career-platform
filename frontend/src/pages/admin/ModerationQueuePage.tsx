import { useState } from 'react';
import { Link } from 'react-router';
import { useModerationService } from '../../admin/moderationContext';
import {
  MODERATION_STATUSES, PRIORITY_LABELS, STATUS_LABELS, TARGET_TYPES, TARGET_TYPE_LABELS, TRIGGER_LABELS,
  moderationErrorMessage,
  type ModerationCaseSummary, type ModerationListQuery, type ModerationStatus, type Priority, type TargetType,
} from '../../api/moderation';
import { useQuery } from '../../api/useQuery';
import { useAuth } from '../../auth/useAuth';
import { DataTable, type TableColumn } from '../../components/DataTable';
import { FilterChips } from '../../components/FilterChips';
import { assigneeLabel } from './moderationFormat';
import { DueDate, ModerationNotice, StatusBadge } from './moderationUi';
import './Moderation.css';

const statusOptions = [{ value: '', label: '전체' }, ...MODERATION_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] }))];
/** 한 번에 불러오는 최대 건수(서버 최대 100). 더 있으면 필터로 좁히도록 안내합니다. */
const QUEUE_LIMIT = 100;
const priorityOptions = [{ value: '', label: '전체' },
  ...([1, 2, 3] as const).map((p) => ({ value: String(p), label: PRIORITY_LABELS[p] }))];

/** UI-027 관리자 검수 큐 (T82). Mock 모드면 Mock Adapter, 아니면 실제 API(T81). */
export function ModerationQueuePage() {
  const service = useModerationService();
  const { state } = useAuth();
  const viewerId = state.status === 'authenticated' ? state.user.userId : undefined;
  const [status, setStatus] = useState('');
  const [targetType, setTargetType] = useState('');
  const [priority, setPriority] = useState('');

  const query: ModerationListQuery = {
    status: (status || undefined) as ModerationStatus | undefined,
    target_type: (targetType || undefined) as TargetType | undefined,
    priority: priority ? (Number(priority) as Priority) : undefined,
    limit: QUEUE_LIMIT,
  };
  const list = useQuery(['moderation-cases', query], (signal) => service.list(query, signal));

  const columns: TableColumn<ModerationCaseSummary>[] = [
    { key: 'case', header: '검수 건', render: (row) => (
      <Link to={`/admin/moderation/${encodeURIComponent(row.case_id)}`}>
        <span className="moderation-id">{row.case_id}</span> {row.target_summary ?? '(대상이 삭제됨)'}
      </Link>) },
    { key: 'type', header: '유형', render: (row) => `${TARGET_TYPE_LABELS[row.target_type]} · ${TRIGGER_LABELS[row.trigger]}` },
    { key: 'status', header: '상태', render: (row) => <StatusBadge status={row.status} /> },
    { key: 'priority', header: '우선순위', render: (row) => PRIORITY_LABELS[row.priority] },
    { key: 'due', header: '처리 기한', render: (row) => <DueDate dueAt={row.due_at} status={row.status} /> },
    { key: 'assignee', header: '담당자', render: (row) => assigneeLabel(row.assignee_id, viewerId) },
  ];

  return (
    <section className="moderation-page" aria-labelledby="moderation-queue-title">
      <h1 id="moderation-queue-title">콘텐츠 검수</h1>
      <ModerationNotice />
      <div className="moderation-filters">
        {/* FilterChips 의 이름은 aria-label 로만 전달되므로 같은 글자를 눈에 보이게 붙입니다(중복 낭독 방지 aria-hidden). */}
        <div className="moderation-filter">
          <span className="moderation-filter__label" aria-hidden="true">상태</span>
          <FilterChips label="상태" options={statusOptions} value={status} onChange={setStatus} />
        </div>
        <div className="moderation-filter">
          <span className="moderation-filter__label" aria-hidden="true">우선순위</span>
          <FilterChips label="우선순위" options={priorityOptions} value={priority} onChange={setPriority} />
        </div>
        <label className="moderation-select">
          콘텐츠 유형
          <select value={targetType} onChange={(event) => setTargetType(event.target.value)}>
            <option value="">전체</option>
            {TARGET_TYPES.map((t) => <option key={t} value={t}>{TARGET_TYPE_LABELS[t]}</option>)}
          </select>
        </label>
      </div>
      <DataTable
        caption="검수 건 목록"
        columns={columns}
        rows={list.status === 'ready' ? list.data.items : []}
        getRowKey={(row) => row.case_id}
        loading={list.status === 'loading' || list.status === 'idle'}
        error={list.status === 'error' ? moderationErrorMessage(list.error).message : undefined}
        onRetry={list.retry}
      />
      {list.status === 'ready' && list.data.next_cursor && (
        <p role="status" className="moderation-hint">
          최대 {QUEUE_LIMIT}건까지 보여 줍니다. 나머지는 상태·우선순위·유형 필터로 좁혀 확인해 주세요.
        </p>
      )}
    </section>
  );
}
