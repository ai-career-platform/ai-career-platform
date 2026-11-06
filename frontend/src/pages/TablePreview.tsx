import { useState } from 'react';
import { DataTable, type TableColumn } from '../components/DataTable';

type PreviewJob = {
  id: string;
  title: string;
  company: string;
  location: string;
};

const columns: TableColumn<PreviewJob>[] = [
  { key: 'title', header: '직무', render: (row) => row.title },
  { key: 'company', header: '기업', render: (row) => row.company },
  { key: 'location', header: '지역', render: (row) => row.location },
];

const rows: PreviewJob[] = [
  {
    id: 'job-1',
    title: '프론트엔드 개발자',
    company: '가상 기업 A',
    location: '서울',
  },
  {
    id: 'job-2',
    title: '백엔드 개발자',
    company: '가상 기업 B',
    location: '부산',
  },
];

type PreviewState = 'ready' | 'loading' | 'empty' | 'error';

export function TablePreview() {
  const [state, setState] = useState<PreviewState>('ready');

  return (
    <div style={{ display: 'grid', gap: '16px' }}>
      <div
        role="group"
        aria-label="표 상태 선택"
        style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}
      >
        {[
          { value: 'ready', label: '정상' },
          { value: 'loading', label: '로딩' },
          { value: 'empty', label: '빈 데이터' },
          { value: 'error', label: '오류' },
        ].map(({ value, label }) => (
          <button
            key={value}
            type="button"
            className="state-panel-action"
            aria-pressed={state === value}
            onClick={() => setState(value as PreviewState)}
          >
            {label}
          </button>
        ))}
      </div>

      <DataTable
        caption="채용공고 예시 — 가상 데이터"
        columns={columns}
        rows={state === 'empty' ? [] : rows}
        getRowKey={(row) => row.id}
        loading={state === 'loading'}
        error={
          state === 'error'
            ? '목록을 불러오지 못했습니다. 다시 시도해 주세요.'
            : undefined
        }
        onRetry={() => setState('ready')}
      />
    </div>
  );
}