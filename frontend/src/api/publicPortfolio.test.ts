/** T130 공개 포트폴리오 HTTP 어댑터: 경로·메서드·본문이 서버 계약(T129, backend/app/routers/public_portfolio.py)과 같은지 확인합니다. */
import { describe, expect, it, vi } from 'vitest';
import { apiFrom, type RequestFn } from '../test/api';

describe('createHttpPortfolioService', () => {
  it('maps each owner call to the T129 endpoint', async () => {
    const request = vi.fn<RequestFn>(async () => ({}));
    const service = apiFrom(request).publicPortfolio;
    await service.settings();
    await service.updateSelection({ fields: ['headline'], experience_ids: ['e-1'], project_ids: [], alias: null, version: 1 });
    await service.preview();
    await service.confirm(2);
    await service.withdraw();
    await service.createLink(30);
    await service.revokeLink('a/b');
    expect(request.mock.calls.map(([path, init]) => [init?.method ?? 'GET', path])).toEqual([
      ['GET', '/v1/me/public-profile'],
      ['PUT', '/v1/me/public-profile/selection'],
      ['GET', '/v1/me/public-profile/preview'],
      ['POST', '/v1/me/public-profile/consent'],
      ['DELETE', '/v1/me/public-profile/consent'],
      ['POST', '/v1/me/public-profile/links'],
      ['DELETE', '/v1/me/public-profile/links/a%2Fb'],
    ]);
    // 서버 모델(extra="forbid"): SelectionUpdate·ConfirmRequest·LinkCreate 필드 그대로
    expect(request.mock.calls[1]![1]).toMatchObject({
      body: { fields: ['headline'], experience_ids: ['e-1'], project_ids: [], alias: null, version: 1 } });
    expect(request.mock.calls[3]![1]).toMatchObject({ body: { version: 2 } });
    expect(request.mock.calls[5]![1]).toMatchObject({ body: { ttl_days: 30 } });
  });

  it('reads own items from the existing profile APIs', async () => {
    const request = vi.fn<RequestFn>(async (path) => (path === '/v1/me/experiences'
      ? [{ experience_id: 'e-1', organization: '가상테크', title: '개발자' }]
      : [{ project_id: 'p-1', title: '추천 시스템' }]));
    const items = await apiFrom(request).publicPortfolio.ownItems();
    expect(items).toEqual({ experiences: [{ id: 'e-1', label: '가상테크 · 개발자' }], projects: [{ id: 'p-1', label: '추천 시스템' }] });
  });

  it('views a public link without sending the login token', async () => {
    const request = vi.fn<RequestFn>(async () => ({ headline: 'x' }));
    await apiFrom(request).publicPortfolio.view('tok/en');
    expect(request).toHaveBeenCalledWith('/v1/public/portfolios/tok%2Fen', expect.objectContaining({ token: null }));
  });
});
