/**
 * T127 기업 공고 관리 콘솔 — 실제 라우터 + Mock HTTP 로그인 + 기업·공고 Mock Adapter(T124·T126 규칙 흉내).
 * Mock 모드 시험입니다. 실제 API 연결(Mock 모드 아님)은 company/PostingServiceProvider.test.tsx 에서 확인합니다.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import type { MockCompanyBackend, MockCompanyOptions } from '../mocks/companyAccounts';
import type { MockPostingBackend, MockPostingOptions } from '../mocks/companyPostings';
import { buildRoutes } from '../routes';

const holder = vi.hoisted(() => ({ company: null as MockCompanyBackend | null, postings: null as MockPostingBackend | null }));
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false } }));
vi.mock('../mocks/companyAccounts', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/companyAccounts')>();
  return { ...original, createMockCompanyBackend: (o: MockCompanyOptions = {}) => (holder.company ??= original.createMockCompanyBackend({ ...o, latencyMs: 0 })) };
});
vi.mock('../mocks/companyPostings', async (importOriginal) => {
  const original = await importOriginal<typeof import('../mocks/companyPostings')>();
  return { ...original, createMockPostingBackend: (c: MockCompanyBackend, o: MockPostingOptions = {}) =>
    (holder.postings ??= original.createMockPostingBackend(c, { ...o, latencyMs: 0 })) };
});

const USER = 'user@example.com';
const ADMIN = 'admin@example.com';
beforeEach(() => { holder.company = null; holder.postings = null; });

async function open(path: string, as: string, companyPostingsUi = true) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, adminAuditUi: false, companyConsoleUi: true, companyPostingsUi }),
    { initialEntries: ['/login'] });
  render(<RouterProvider router={router} />);
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: as } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
  await screen.findByRole('heading', { name: '내 계정' });
  await act(() => router.navigate(path));
  return router;
}
const orgId = (name: string) => holder.company!.snapshot().orgs.find((o) => o.name === name)!.organization_id;
const postingId = (title: string) => holder.postings!.rows().find((r) => r.title === title)!.posting_id;
async function openPostings(org = '가상테크 (Mock)') {
  await open('/company', USER);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(org.split(' ')[0]!) }));
  fireEvent.click(await screen.findByRole('link', { name: '공고 관리 (T127)' }));
  await screen.findByLabelText('새 공고 제목');
  return screen.queryByRole('table', { name: /공고 \d+건/ })!;
}
const openPosting = async (title: string) => {
  fireEvent.click(await screen.findByRole('button', { name: `${title} 열기` }));
  return screen.findByRole('heading', { level: 2, name: new RegExp(title.replace(/[()]/g, '.')) });
};

describe('feature flag and access', () => {
  it('postings flag off: no link in the console and the URL is not found', async () => {
    await open('/company', USER, false);
    fireEvent.click(await screen.findByRole('button', { name: /가상테크/ }));
    await screen.findByRole('table', { name: /조직 멤버/ });
    expect(screen.queryByRole('link', { name: '공고 관리 (T127)' })).not.toBeInTheDocument();
    cleanup();
    await open('/company/postings?org=x', USER, false);
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
  });

  it('the flag needs the company console flag and its own flag; the mock adapter is used only in mock mode', () => {
    const envText = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    expect(envText).toContain("companyPostingsUi: import.meta.env.VITE_COMPANY_CONSOLE_UI === 'true' && import.meta.env.VITE_COMPANY_POSTINGS_UI === 'true'");
    const provider = readFileSync(resolve(cwd(), 'src/company/PostingServiceProvider.tsx'), 'utf8');
    expect(provider).toMatch(/env\.mockEnabled\s*\?\s*createMockPostingBackend/);
    expect(provider).toContain('api.companyPostings');
    expect(provider).not.toMatch(/fetch\(/);
  });

  it('no organization chosen and another company are handled', async () => {
    await open('/company/postings', USER);
    expect(await screen.findByText('조직을 먼저 고르세요')).toBeInTheDocument();
    cleanup();
    await open(`/company/postings?org=${'unknown'}`, ADMIN);
    expect(await screen.findByText('조직을 찾을 수 없거나 접근 권한이 없습니다')).toBeInTheDocument();
    cleanup();
    await open(`/company/postings?org=${orgId('가상테크 (Mock)')}`, ADMIN);
    expect(await screen.findByText('조직을 찾을 수 없거나 접근 권한이 없습니다')).toBeInTheDocument();
    expect(screen.queryByText('백엔드 개발자 (가상)')).not.toBeInTheDocument();
  });
});

describe('list, detail and transitions', () => {
  it('lists postings with status badges and filters by status', async () => {
    const table = await openPostings();
    expect(within(table).getAllByRole('row')).toHaveLength(6);
    for (const label of ['초안', '검수 대기', '반려', '게시 중', '만료']) expect(within(table).getByText(label)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '반려 1' }));
    expect(within(await screen.findByRole('table', { name: '공고 1건' })).getByText('QA 엔지니어 (가상)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '반려 1' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('there is no publish, reject or take-down control anywhere for companies', async () => {
    await openPostings();
    for (const title of ['데이터 엔지니어 (초안, 가상)', '프론트엔드 개발자 (가상)', '백엔드 개발자 (가상)']) {
      await openPosting(title);
      expect(screen.queryByRole('button', { name: /^(게시|게시하기|승인|반려|반려하기|운영 내림|내리기)$/ })).not.toBeInTheDocument();
    }
  });

  it('shows the rejection reason; editing returns the posting to draft and clears the reason', async () => {
    await openPostings();
    await openPosting('QA 엔지니어 (가상)');
    expect(screen.getByText('반려 사유: 개인 연락처 게시')).toBeInTheDocument();
    expect(screen.getByText(/회사 채용 메일로 바꿔 주세요/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('직무 설명 (필수)'), { target: { value: '연락은 recruit@example.invalid 로' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(await screen.findByRole('status')).toHaveTextContent('저장했습니다.');
    expect(within(screen.getByRole('table')).getAllByText('초안')).toHaveLength(2);
    expect(screen.queryByText(/반려 사유:/)).not.toBeInTheDocument();
  });

  it('submitting an incomplete draft explains what is missing, completing it moves to review', async () => {
    await openPostings();
    await openPosting('데이터 엔지니어 (초안, 가상)');
    fireEvent.click(screen.getByRole('button', { name: '검수 요청' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('필수 항목(제목·설명·고용형태·근무지·마감일)');
    fireEvent.change(screen.getByLabelText('직무 설명 (필수)'), { target: { value: '데이터 파이프라인 운영 (가상)' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await screen.findByRole('status');
    fireEvent.click(screen.getByRole('button', { name: '검수 요청' }));
    expect(await screen.findByRole('status')).toHaveTextContent('검수를 요청했습니다.');
    expect(await screen.findByText('검수 대기 중입니다. 내용을 고치려면 요청을 철회하세요.')).toBeInTheDocument();
    expect(screen.queryByLabelText('직무 설명 (필수)')).not.toBeInTheDocument();
  });

  it('https-only apply link is enforced', async () => {
    await openPostings();
    await openPosting('데이터 엔지니어 (초안, 가상)');
    fireEvent.change(screen.getByLabelText('지원 링크 (https)'), { target: { value: 'http://insecure.example.invalid' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('https 주소');
  });

  it('withdraws a pending review back to draft', async () => {
    await openPostings();
    await openPosting('프론트엔드 개발자 (가상)');
    fireEvent.click(screen.getByRole('button', { name: '검수 요청 철회' }));
    expect(await screen.findByRole('status')).toHaveTextContent('초안으로 돌아갔습니다');
    expect(await screen.findByRole('button', { name: '검수 요청' })).toBeInTheDocument();
  });

  it('a decision made elsewhere makes the stale action fail with 409 and reloads the real status', async () => {
    await openPostings();
    await openPosting('프론트엔드 개발자 (가상)');
    holder.postings!.review(postingId('프론트엔드 개발자 (가상)'), 'approve');   // 운영자가 그사이 승인
    fireEvent.click(screen.getByRole('button', { name: '검수 요청 철회' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('다른 사람이 먼저 바꿨거나');
    await waitFor(() => expect(within(screen.getByRole('table')).getAllByText('게시 중')).toHaveLength(2));
  });

  it('closes a published posting after confirmation and creates a revision without touching the live one', async () => {
    await openPostings();
    await openPosting('백엔드 개발자 (가상)');
    fireEvent.click(screen.getByRole('button', { name: '수정본 만들기' }));
    expect(await screen.findByRole('status')).toHaveTextContent('승인되기 전까지 공개 공고는 그대로입니다');
    expect(await screen.findByText('(수정본)')).toBeInTheDocument();
    expect(holder.postings!.rows().find((r) => r.title === '백엔드 개발자 (가상)' && !r.revision_of)!.status).toBe('published');
    // 목록은 최근 수정순: [수정본, 원본] — 원본을 열어 마감
    fireEvent.click(screen.getAllByRole('button', { name: '백엔드 개발자 (가상) 열기' })[1]!);
    fireEvent.click(await screen.findByRole('button', { name: '마감' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '마감' }));
    expect(await screen.findByRole('status')).toHaveTextContent('공개 목록에서 바로 내려갑니다');
  });

  it('a pending (unverified) organization can draft but cannot request review (403)', async () => {
    await openPostings('검증대기랩 (Mock)');
    fireEvent.change(screen.getByLabelText('새 공고 제목'), { target: { value: '첫 공고 (가상)' } });
    fireEvent.click(screen.getByRole('button', { name: '초안 만들기' }));
    expect(await screen.findByRole('status')).toHaveTextContent('초안을 만들었습니다');
    const id = postingId('첫 공고 (가상)');
    await act(async () => {
      await holder.postings!.serviceFor(USER).edit(orgId('검증대기랩 (Mock)'), id, { description: 'd', employment_type: 'intern',
        location_text: '서울', expires_at: new Date(Date.now() + 86_400_000).toISOString() }, 1);
    });
    cleanup();
    await open(`/company/postings?org=${orgId('검증대기랩 (Mock)')}&posting=${id}`, USER);
    fireEvent.click(await screen.findByRole('button', { name: '검수 요청' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('운영 확인이 끝난 조직만 검수를 요청할 수 있습니다.');
  });

  it('load failure shows retry', async () => {
    await open('/company', USER);
    await screen.findByRole('button', { name: /가상테크/ });
    cleanup();
    await open(`/company/postings?org=${orgId('가상테크 (Mock)')}`, USER);
    await screen.findByRole('table', { name: /공고/ });
    cleanup();
    holder.postings!.failNext('load');
    await open(`/company/postings?org=${orgId('가상테크 (Mock)')}`, USER);
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('table', { name: /공고 \d+건/ })).toBeInTheDocument();
  });
});
