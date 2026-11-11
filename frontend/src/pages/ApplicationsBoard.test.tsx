/**
 * T103 개인 지원 현황 보드 — 실제 라우터(buildRoutes) + Mock HTTP 로그인 + 지원 현황 Mock Adapter.
 * 실제 API(T102)는 기능 플래그 뒤라 연결하지 않았습니다(Mock PASS 이며 실제 API PASS 아님).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { STAGES, TRANSITIONS } from '../api/jobApplications';
import { MOCK_PASSWORD } from '../mocks/handlers';
import type { MockApplicationBackend, MockApplicationOptions } from '../mocks/jobApplications';
import { buildRoutes } from '../routes';

const holder = vi.hoisted(() => ({
  backend: null as MockApplicationBackend | null,
  seed: undefined as MockApplicationOptions['seed'],
}));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false, applicationsUi: false } }));
vi.mock('../mocks/jobApplications', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/jobApplications')>();
  return {
    ...original,
    createMockApplicationBackend: (options: MockApplicationOptions = {}) => {
      holder.backend ??= original.createMockApplicationBackend({ ...options, latencyMs: 0, seed: holder.seed });
      return holder.backend;
    },
  };
});

const USER = 'user@example.com';
const ADMIN = 'admin@example.com';
beforeEach(() => { holder.backend = null; holder.seed = undefined; });

async function open(path: string, as?: string, applicationsUi = true) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: false, applicationsUi }),
    { initialEntries: [as ? '/login' : path] });
  render(<RouterProvider router={router} />);
  if (as) {
    fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: as } });
    fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await screen.findByRole('link', { name: as === ADMIN ? '운영 관리자' : '일반 사용자' });
    // 로그인 완료 후 계정 화면으로 이동이 확정되어야 딥링크를 덮어쓰지 않는다.
    await screen.findByRole('heading', { name: '내 계정' });
    await act(() => router.navigate(path));
  }
  return router;
}
const column = (label: RegExp) => screen.getByRole('region', { name: label });
const cardTitles = (label: RegExp) => within(column(label)).queryAllByRole('listitem').map((li) => li.querySelector('strong')?.textContent);
const stageSelect = (title: string) => {
  const card = screen.getByText(title).closest('li')!;
  return within(card).getByLabelText('단계') as HTMLSelectElement;
};

describe('feature flag and access', () => {
  it('flag off: no menu and the URL is not found', async () => {
    await open('/me/applications', USER, false);
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '지원 현황 (Mock)' })).not.toBeInTheDocument();
  });

  it('default routes keep it off, the flag needs mock mode, and no HTTP adapter is wired', async () => {
    const { routes } = await import('../routes');
    expect(JSON.stringify(routes, (k, v) => (k === 'element' ? undefined : v))).not.toContain('me/applications');
    expect(readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8'))
      .toContain("applicationsUi: import.meta.env.VITE_API_MOCK === 'true' && import.meta.env.VITE_APPLICATIONS_UI === 'true'");
    expect(readFileSync(resolve(cwd(), 'src/applications/ApplicationServiceProvider.tsx'), 'utf8')).not.toMatch(/^import .*(createHttp|useApi)|fetch\(/m);
  });

  it('anonymous users go to login', async () => {
    await open('/me/applications');
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
  });
});

describe('board', () => {
  it('shows the not-official notice, stage columns with counts, and closed or missing postings', async () => {
    await open('/me/applications', USER);
    expect(await screen.findByText(/기업의 공식 결과가 아니며/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '지원 현황 (Mock)' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      '관심 1건', '지원 준비 1건', '지원 완료 2건', '면접 진행 1건', '합격·제안(내 기록) 0건', '불합격(내 기록) 1건', '지원 취소 0건']);
    expect(within(screen.getByText('QA 엔지니어 (가상)').closest('li')!).getByText('마감된 공고')).toBeInTheDocument();
    expect(within(screen.getByText('모바일 개발자 (가상)').closest('li')!).getByText('공고 정보 없음')).toBeInTheDocument();
    expect([...stageSelect('백엔드 개발자 (가상)').options].map((o) => o.textContent)).toEqual(['관심', '지원 준비', '지원 완료', '지원 취소']);
    expect([...stageSelect('모바일 개발자 (가상)').options].map((o) => o.value)).toEqual(['rejected', 'interviewing']);
  });

  it('moving a card saves it, moves it to the new column and sets the applied date', async () => {
    await open('/me/applications', USER);
    await screen.findByText('백엔드 개발자 (가상)');
    fireEvent.change(stageSelect('백엔드 개발자 (가상)'), { target: { value: 'applied' } });
    expect(await screen.findByRole('status')).toHaveTextContent('단계를 ‘지원 완료’(으)로 바꿨습니다.');
    await waitFor(() => expect(cardTitles(/^지원 완료/)).toContain('백엔드 개발자 (가상)'));
    expect(cardTitles(/^관심/)).toEqual([]);
    const saved = holder.backend!.snapshot(USER).find((x) => x.posting.title === '백엔드 개발자 (가상)')!;
    expect(saved).toMatchObject({ stage: 'applied', version: 2 });
    expect(saved.applied_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(within(screen.getByText('백엔드 개발자 (가상)').closest('li')!).getByText('지원일(내 기록)')).toBeInTheDocument();
  });

  it('a failed save rolls the card back and announces it', async () => {
    await open('/me/applications', USER);
    await screen.findByText('데이터 엔지니어 (가상)');
    holder.backend!.failNext('update');
    fireEvent.change(stageSelect('데이터 엔지니어 (가상)'), { target: { value: 'applied' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('데이터 엔지니어 (가상): 서버에 연결하지 못했습니다. 원래 상태로 되돌렸습니다.');
    expect(cardTitles(/^지원 준비/)).toEqual(['데이터 엔지니어 (가상)']);
    expect(holder.backend!.snapshot(USER).find((x) => x.posting.title === '데이터 엔지니어 (가상)')!.stage).toBe('preparing');
  });

  it('an edit from another tab (409) reloads the latest data instead of overwriting it', async () => {
    await open('/me/applications', USER);
    await screen.findByText('서버 개발자 (가상)');
    const other = holder.backend!.serviceFor(USER);
    const target = holder.backend!.snapshot(USER).find((x) => x.posting.title === '서버 개발자 (가상)')!;
    await other.update(target.application_id, { version: 1, stage: 'offered' });          // 다른 탭
    fireEvent.change(stageSelect('서버 개발자 (가상)'), { target: { value: 'rejected' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('다른 곳에서 먼저 바뀌었거나');
    await waitFor(() => expect(cardTitles(/^합격·제안/)).toEqual(['서버 개발자 (가상)']));
    expect(holder.backend!.snapshot(USER).find((x) => x.application_id === target.application_id)!.stage).toBe('offered');
  });

  it('memo saves; delete asks first, cancel keeps it, confirm removes it', async () => {
    await open('/me/applications', USER);
    const card = (await screen.findByText('프론트엔드 개발자 (가상)')).closest('li')!;
    fireEvent.click(within(card).getByText('메모', { selector: 'summary' }));
    fireEvent.change(within(card).getByLabelText('메모'), { target: { value: '코딩 테스트 일정 확인' } });
    fireEvent.click(within(card).getByRole('button', { name: '메모 저장' }));
    expect(await screen.findByRole('status')).toHaveTextContent('메모를 저장했습니다.');
    expect(holder.backend!.snapshot(USER).find((x) => x.posting.title === '프론트엔드 개발자 (가상)')!.memo).toBe('코딩 테스트 일정 확인');

    fireEvent.click(screen.getByRole('button', { name: '프론트엔드 개발자 (가상) 기록 삭제' }));
    const dialog = await screen.findByRole('dialog', { name: '지원 기록을 삭제할까요?' });
    fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(holder.backend!.snapshot(USER)).toHaveLength(6);
    fireEvent.click(screen.getByRole('button', { name: '프론트엔드 개발자 (가상) 기록 삭제' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '삭제' }));
    expect(await screen.findByRole('status')).toHaveTextContent('기록을 삭제했습니다.');
    expect(screen.queryByText('프론트엔드 개발자 (가상)')).not.toBeInTheDocument();
    expect(holder.backend!.snapshot(USER)).toHaveLength(5);
  });

  it('the table view lists the same records', async () => {
    await open('/me/applications', USER);
    fireEvent.click(await screen.findByRole('button', { name: '표' }));
    const table = screen.getByRole('table', { name: '지원 기록 표 (내가 기록한 상태)' });
    expect(within(table).getAllByRole('row')).toHaveLength(7);
    expect(within(table).getByRole('rowheader', { name: 'QA 엔지니어 (가상)' }).closest('tr')).toHaveTextContent('마감된 공고');
    expect(screen.getByRole('button', { name: '표' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps users apart', async () => {
    await open('/me/applications', USER);
    await screen.findByText('백엔드 개발자 (가상)');
    fireEvent.change(stageSelect('백엔드 개발자 (가상)'), { target: { value: 'withdrawn' } });
    await screen.findByRole('status');
    cleanup();
    await open('/me/applications', ADMIN);
    await waitFor(() => expect(cardTitles(/^관심/)).toEqual(['백엔드 개발자 (가상)']));      // 관리자 자신의 기록은 그대로
    const userId = holder.backend!.snapshot(USER)[0]!.application_id;
    await expect(holder.backend!.serviceFor(ADMIN).update(userId, { version: 2, memo: 'x' })).rejects.toMatchObject({ status: 404 });
    await expect(holder.backend!.serviceFor(ADMIN).remove(userId)).rejects.toMatchObject({ status: 404 });
  });

  it('shows the empty state with a link to job postings, and a load error with retry', async () => {
    holder.seed = () => [];
    await open('/me/applications', USER);
    expect(await screen.findByText('아직 기록한 지원이 없습니다')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '채용공고 탐색하기' })).toHaveAttribute('href', '/job-postings');
    cleanup();
    holder.backend = null; holder.seed = undefined;
    const router = await open('/account', USER);
    await act(() => router.navigate('/me/applications'));
    await screen.findByText('백엔드 개발자 (가상)');
    holder.backend!.failNext('list');
    await act(() => router.navigate('/account'));
    await act(() => router.navigate('/me/applications'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('지원 기록을 불러오지 못했습니다');
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('백엔드 개발자 (가상)')).toBeInTheDocument();
  });
});

describe('rules match the T101 contract', () => {
  it('the transition table equals the T101 §4 document table', () => {
    const doc = readFileSync(resolve(cwd(), '../docs/applications/T101_APPLICATION_TRACKING_CONTRACT.md'), 'utf8');
    const moves = doc.split('## 4.')[1]!.split('\n## ')[0]!.split('허용 이동')[1]!;
    const table = Object.fromEntries([...moves.matchAll(/^\| `([a-z]+)` \| (.+) \|$/gm)]
      .map((m) => [m[1], [...m[2]!.matchAll(/`([a-z]+)`/g)].map((x) => x[1]).sort()]));
    expect(table).toEqual(Object.fromEntries(STAGES.map((s) => [s, [...TRANSITIONS[s]].sort()])));
  });

  it('the mock rejects a move outside the table and a stale version with 409', async () => {
    const { createMockApplicationBackend } = await vi.importActual<typeof import('../mocks/jobApplications')>('../mocks/jobApplications');
    const backend = createMockApplicationBackend();
    const svc = backend.serviceFor('u1');
    const interested = backend.snapshot('u1').find((x) => x.stage === 'interested')!;
    await expect(svc.update(interested.application_id, { version: 1, stage: 'offered' })).rejects.toMatchObject({ status: 409, code: 'CONFLICT' });
    await svc.update(interested.application_id, { version: 1, stage: 'preparing' });
    await expect(svc.update(interested.application_id, { version: 1, memo: 'x' })).rejects.toMatchObject({ status: 409 });
    const back = await svc.update(interested.application_id, { version: 2, stage: 'interested' });
    expect(back.applied_on).toBeNull();
  });
});
