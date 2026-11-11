/**
 * UI-005 알림 수신 설정 (T97, F-005). T95 제안 계약: 필수 알림은 끌 수 없고, 선택 알림은 켜고 끌 때마다 동의 이력이 남습니다.
 * - 마케팅·추천 알림은 동의 전 기본 꺼짐(화면이 임의로 켜지 않음).
 * - 바꾸면 바로 저장하고, 저장에 실패하면 원래 값으로 되돌린 뒤 알립니다.
 * 지금은 Mock Adapter 만 연결됩니다(수신 설정 API 는 T95 제안, 서버 미구현).
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { TYPE_LABELS, notificationErrorMessage, type NotificationPreference } from '../api/notifications';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { StatePanel } from '../components/StatePanel';
import { useNotificationService } from '../notifications/notificationContext';
import './Notifications.css';

export function NotificationSettingsPage() {
  const service = useNotificationService();
  const { state } = useAuth();
  const userId = state.status === 'authenticated' ? state.user.userId : null;
  const prefs = useQuery(['me-notification-preferences', userId], (signal) => service.getPreferences(signal));
  const [saving, setSaving] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: 'error' | 'ok'; text: string } | null>(null);

  async function toggle(pref: NotificationPreference, enabled: boolean) {
    if (pref.required) return;
    const label = TYPE_LABELS[pref.type].label;
    setSaving(pref.type); setMessage(null);
    prefs.setData((data) => ({ items: data.items.map((p) => (p.type === pref.type ? { ...p, enabled } : p)) }));
    try {
      const saved = await service.updatePreferences({ items: [{ type: pref.type, enabled }] });
      prefs.setData(() => saved);
      setMessage({ kind: 'ok', text: `${label} 알림을 ${enabled ? '받습니다' : '받지 않습니다'}. 동의 이력에 기록됩니다.` });
    } catch (error) {
      prefs.setData((data) => ({ items: data.items.map((p) => (p.type === pref.type ? { ...p, enabled: pref.enabled } : p)) }));
      setMessage({ kind: 'error', text: `${label}: ${notificationErrorMessage(error, '저장하지 못했습니다. 원래 설정으로 되돌렸습니다.')}` });
    } finally {
      setSaving(null);
    }
  }

  const groups = prefs.status === 'ready'
    ? [...new Set(prefs.data.items.map((p) => TYPE_LABELS[p.type].group))]
    : [];

  return (
    <section className="notify-page" aria-labelledby="notify-settings-title">
      <h1 id="notify-settings-title">알림 수신 설정</h1>
      <p className="notify-notice">가상 데이터(Mock)입니다. 실제 알림 발송·서버 연동은 아직 없습니다.</p>
      <p>
        계정 보안·계정 안내·법적 고지는 필수 알림이라 끌 수 없습니다. 선택 알림은 언제든 켜고 끌 수 있으며,
        광고성 알림은 밤 9시부터 아침 8시까지 보내지 않습니다.
      </p>
      <p><Link to="/me/notifications">알림함으로 돌아가기</Link></p>
      {message && (
        <p className={message.kind === 'error' ? 'notify-error' : 'notify-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
        </p>
      )}
      {(prefs.status === 'loading' || prefs.status === 'idle') && <StatePanel variant="loading" title="설정을 불러오는 중입니다" />}
      {prefs.status === 'error' && (
        <StatePanel variant="error" title="설정을 불러오지 못했습니다"
          description={notificationErrorMessage(prefs.error, '잠시 후 다시 시도해 주세요.')} actionLabel="다시 시도" onAction={prefs.retry} />
      )}
      {prefs.status === 'ready' && groups.map((group) => (
        <fieldset key={group} className="notify-group">
          <legend>{group}</legend>
          {prefs.data.items.filter((p) => TYPE_LABELS[p.type].group === group).map((pref) => {
            const meta = TYPE_LABELS[pref.type];
            const hint = `${pref.type}-hint`;
            return (
              <div key={pref.type} className="notify-pref">
                <label>
                  <input type="checkbox" checked={pref.enabled} disabled={pref.required || saving !== null}
                    aria-describedby={hint} onChange={(e) => toggle(pref, e.target.checked)} />
                  {meta.label}
                </label>
                <span id={hint} className="notify-hint">
                  {pref.required ? '필수 알림 — 끌 수 없음' : pref.enabled ? '받는 중' : '받지 않음'} · {meta.description}
                </span>
              </div>
            );
          })}
        </fieldset>
      ))}
    </section>
  );
}
