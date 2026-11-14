/** T97 알림함·수신 설정 HTTP 어댑터: 경로·메서드·본문이 서버 계약(T97 API)과 같은지 확인합니다. */
import { describe, expect, it, vi } from 'vitest';
import { apiFrom, type RequestFn } from '../test/api';

describe('createHttpNotificationService', () => {
  it('maps each call to the T97 endpoint', async () => {
    const request = vi.fn<RequestFn>(async () => ({}));
    const service = apiFrom(request).notifications;
    await service.listInbox();
    await service.markRead('a/b');
    await service.markAllRead();
    await service.getPreferences();
    await service.updatePreferences({ items: [{ type: 'marketing.newsletter', enabled: true }] });
    expect(request.mock.calls.map(([path, init]) => [init?.method ?? 'GET', path])).toEqual([
      ['GET', '/v1/me/notifications'],
      ['POST', '/v1/me/notifications/a%2Fb/read'],
      ['POST', '/v1/me/notifications/read-all'],
      ['GET', '/v1/me/notification-preferences'],
      ['PUT', '/v1/me/notification-preferences'],
    ]);
    expect(request.mock.calls[4]![1]).toMatchObject({ body: { items: [{ type: 'marketing.newsletter', enabled: true }] } });
  });
});
