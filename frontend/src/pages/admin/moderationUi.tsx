import { STATUS_LABELS, type ModerationStatus } from '../../api/moderation';
import { formatDateTime, isOverdue } from './moderationFormat';

/** 모든 검수 화면 상단 안내. 실제 서비스 연동·정책 확정이 아님을 항상 보여 줍니다. */
export function ModerationNotice() {
  return (
    <p className="moderation-notice" role="note">
      가상 데이터(Mock) 화면입니다. 검수 API(T81)가 아직 없고, 검수 정책(T80)은 PM 승인 전 제안입니다.
      여기서 한 조치는 이 브라우저 메모리에만 남고 실제 콘텐츠에 반영되지 않습니다.
    </p>
  );
}

/** 상태는 색과 함께 글자로도 표시합니다. */
export function StatusBadge({ status }: { status: ModerationStatus }) {
  return <span className={`moderation-status moderation-status--${status.toLowerCase()}`}>{STATUS_LABELS[status]}</span>;
}

/** 처리 기한. 열린 건이 기한을 넘기면 "기한 초과"를 글자로 붙입니다. */
export function DueDate({ dueAt, status }: { dueAt: string; status: ModerationStatus }) {
  const overdue = isOverdue(dueAt, status);
  return (
    <span className={overdue ? 'moderation-overdue' : undefined}>
      {formatDateTime(dueAt)}{overdue ? ' (기한 초과)' : ''}
    </span>
  );
}
