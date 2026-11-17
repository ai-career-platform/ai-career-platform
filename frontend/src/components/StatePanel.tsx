import './StatePanel.css';

type StatePanelProps = {
  variant: 'loading' | 'empty' | 'error' | 'unauthorized';
  title?: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  /** 오류 응답의 X-Request-ID(displayRequestId). 있을 때만 문의용 요청 번호로 표시합니다. */
  requestId?: string;
};

const defaultContent = {
  loading: {
    title: '불러오는 중입니다',
    description: '잠시만 기다려 주세요.',
  },
  empty: {
    title: '표시할 데이터가 없습니다',
    description: '조건을 변경하거나 새로운 항목을 추가해 주세요.',
  },
  error: {
    title: '불러오지 못했습니다',
    description: '잠시 후 다시 시도해 주세요.',
  },
  unauthorized: {
    title: '접근 권한이 없습니다',
    description: '현재 계정의 접근 권한을 확인해 주세요.',
  },
};

export function StatePanel({
  variant,
  title,
  description,
  actionLabel,
  onAction,
  requestId,
}: StatePanelProps) {
  const content = defaultContent[variant];
  const isLoading = variant === 'loading';

  return (
    <div
      className={`state-panel state-panel--${variant}`}
      role={variant === 'error' ? 'alert' : 'status'}
      aria-busy={isLoading}
    >
      {isLoading && <span className="state-spinner" aria-hidden="true" />}

      <p className="state-panel-title">{title ?? content.title}</p>
      <p className="state-panel-description">
        {description ?? content.description}
      </p>

      {variant === 'error' && requestId && (
        <p className="state-panel-request-id">
          문의용 요청 번호: <code className="state-panel-request-id-value">{requestId}</code>
        </p>
      )}

      {!isLoading && actionLabel && onAction && (
        <button
          type="button"
          className="state-panel-action"
          onClick={onAction}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}