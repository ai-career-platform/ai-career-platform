import type { Key, ReactNode } from 'react';
import { StatePanel } from './StatePanel';
import './DataTable.css';

export type TableColumn<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
};

type DataTableProps<T> = {
  caption: string;
  columns: TableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => Key;
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
};

export function DataTable<T>({
  caption,
  columns,
  rows,
  getRowKey,
  loading = false,
  error,
  onRetry,
}: DataTableProps<T>) {
  if (loading) {
    return <StatePanel variant="loading" title={`${caption} 불러오는 중`} />;
  }

  if (error) {
    return (
      <StatePanel
        variant="error"
        title={`${caption} 불러오기 실패`}
        description={error}
        actionLabel={onRetry ? '다시 시도' : undefined}
        onAction={onRetry}
      />
    );
  }

  if (rows.length === 0) {
    return <StatePanel variant="empty" title={`${caption}: 데이터가 없습니다`} />;
  }

  return (
    <div
      className="data-table-scroll"
      role="region"
      aria-label={`${caption} 표 영역`}
      tabIndex={0}
    >
      <table className="data-table">
        <caption>{caption}</caption>

        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={getRowKey(row)}>
              {columns.map((column) => (
                <td key={column.key}>{column.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}