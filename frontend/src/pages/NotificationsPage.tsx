/**
 * UI-N04 알림함 (T97, F-003). 읽음/안 읽음 목록, 한 건·전체 읽음 처리.
 * Mock 모드면 Mock Adapter, 아니면 실제 API(T97, docs/testing/T97_NOTIFICATION_UI_VALIDATION.md §3).
 * 안 읽음은 색만이 아니라 "안 읽음" 글자와 굵은 제목으로 표시합니다.
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { TYPE_LABELS, notificationErrorMessage, type InboxItem } from '../api/notifications';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { StatePanel } from '../components/StatePanel';
import { env } from '../config/env';
import { useNotificationService } from '../notifications/notificationContext';
import './Notifications.css';

const formatter = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Seoul' });

export function NotificationsPage() {
  const service = useNotificationService();
  const { state } = useAuth();
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const inbox = useQuery(['me-notifications', userId], (signal) => service.listInbox(signal));
  const [pending, setPending] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: 'error' | 'ok'; text: string } | null>(null);

  async function markRead(item: InboxItem) {
    setPending(item.notification_id); setMessage(null);
    try {
      const updated = await service.markRead(item.notification_id);
      inbox.setData((page) => ({
        items: page.items.map((x) => (x.notification_id === updated.notification_id ? updated : x)),
        unread_count: page.items.filter((x) => !x.read_at && x.notification_id !== updated.notification_id).length,
      }));
      setMessage({ kind: 'ok', text: `‘${item.title}’을 읽음으로 표시했습니다.` });
    } catch (error) {
      setMessage({ kind: 'error', text: notificationErrorMessage(error, '읽음 처리에 실패했습니다. 다시 시도해 주세요.') });
    } finally {
      setPending(null);
    }
  }

  async function markAll() {
    setPending('all'); setMessage(null);
    try {
      const { updated } = await service.markAllRead();
      const at = new Date().toISOString();
      inbox.setData((page) => ({ items: page.items.map((x) => ({ ...x, read_at: x.read_at ?? at })), unread_count: 0 }));
      setMessage({ kind: 'ok', text: `${updated}건을 읽음으로 표시했습니다.` });
    } catch (error) {
      setMessage({ kind: 'error', text: notificationErrorMessage(error, '읽음 처리에 실패했습니다. 다시 시도해 주세요.') });
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="notify-page" aria-labelledby="notify-title">
      <h1 id="notify-title">알림함</h1>
      {env.mockEnabled && <p className="notify-notice">가상 데이터(Mock)입니다. 실제 알림 발송·서버 연동은 아직 없습니다.</p>}
      <p><Link to="/me/notification-settings">알림 수신 설정</Link></p>
      {message && (
        <p className={message.kind === 'error' ? 'notify-error' : 'notify-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
        </p>
      )}
      {(inbox.status === 'loading' || inbox.status === 'idle') && <StatePanel variant="loading" title="알림을 불러오는 중입니다" />}
      {inbox.status === 'error' && (
        <StatePanel variant="error" title="알림을 불러오지 못했습니다"
          description={notificationErrorMessage(inbox.error, '잠시 후 다시 시도해 주세요.')} actionLabel="다시 시도" onAction={inbox.retry} />
      )}
      {inbox.status === 'ready' && inbox.data.items.length === 0 && (
        <StatePanel variant="empty" title="받은 알림이 없습니다" description="새 알림이 오면 여기에 표시됩니다." />
      )}
      {inbox.status === 'ready' && inbox.data.items.length > 0 && (
        <>
          <div className="notify-toolbar">
            <p id="notify-count" aria-live="polite">안 읽은 알림 {inbox.data.unread_count}건</p>
            <Button variant="outline" onClick={markAll} disabled={pending !== null || inbox.data.unread_count === 0}>
              모두 읽음으로 표시
            </Button>
          </div>
          <ul className="notify-list" aria-describedby="notify-count">
            {inbox.data.items.map((item) => {
              const unread = !item.read_at;
              return (
                <li key={item.notification_id} className={unread ? 'notify-item notify-item--unread' : 'notify-item'}>
                  <div className="notify-item__head">
                    <span className="notify-tag">{TYPE_LABELS[item.type].group}</span>
                    {unread && <span className="notify-unread">안 읽음</span>}
                    <time dateTime={item.created_at}>{formatter.format(new Date(item.created_at))}</time>
                  </div>
                  <h2 className="notify-item__title">{item.title}</h2>
                  <p>{item.summary}</p>
                  {unread && (
                    <Button variant="outline" onClick={() => markRead(item)} disabled={pending !== null}
                      aria-label={`${item.title} 읽음으로 표시`}>
                      읽음으로 표시
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
