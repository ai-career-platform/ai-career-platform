/**
 * T89 접근성 회귀 — 실제 라우터(buildRoutes) + Mock HTTP 로그인으로 주요 화면을 열고 공통 규칙을 자동 점검합니다.
 * 자동 점검은 스크린리더 사용성 전체를 보장하지 않습니다(실제 낭독·순서 체감은 수동 확인 필요).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { buildRoutes } from '../routes';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: true, adminAuditUi: true, notificationsUi: true, jobSearchAdvancedUi: true, applicationsUi: true, companyConsoleUi: true } }));

type Issue = string;

/** 화면 공통 규칙. 문제 목록을 돌려줍니다(빈 배열 = 통과). */
export function audit(root: HTMLElement): Issue[] {
  const issues: Issue[] = [];
  const named = (el: Element) => {
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy && labelledBy.split(/\s+/).some((id) => document.getElementById(id)?.textContent?.trim())) return true;
    if (el.getAttribute('aria-label')?.trim()) return true;
    if ((el as HTMLInputElement).labels?.length && [...(el as HTMLInputElement).labels!].some((l) => l.textContent?.trim())) return true;
    if (el.getAttribute('title')?.trim()) return true;
    return false;
  };
  for (const el of root.querySelectorAll('input:not([type=hidden]), select, textarea')) {
    if (!named(el)) issues.push(`unlabeled control <${el.tagName.toLowerCase()} name="${el.getAttribute('name') ?? ''}">`);
  }
  for (const el of root.querySelectorAll('button, [role=button]')) {
    if (!el.textContent?.trim() && !named(el)) issues.push(`button without accessible name: ${el.outerHTML.slice(0, 80)}`);
  }
  for (const el of root.querySelectorAll('a[href]')) {
    if (!el.textContent?.trim() && !named(el) && !el.querySelector('img[alt]:not([alt=""])')) {
      issues.push(`link without accessible name: ${el.getAttribute('href')}`);
    }
  }
  for (const el of root.querySelectorAll('img')) if (!el.hasAttribute('alt')) issues.push(`img without alt: ${el.getAttribute('src')}`);
  for (const el of root.querySelectorAll('[role=button]:not(button)')) {
    if (el.getAttribute('tabindex') === null) issues.push(`role=button not focusable: ${el.outerHTML.slice(0, 80)}`);
  }
  for (const el of root.querySelectorAll('[tabindex]')) {
    if (Number(el.getAttribute('tabindex')) > 0) issues.push(`positive tabindex breaks tab order: ${el.outerHTML.slice(0, 80)}`);
  }
  const ids = [...root.querySelectorAll('[id]')].map((el) => el.id);
  for (const dup of new Set(ids.filter((value, i) => ids.indexOf(value) !== i))) issues.push(`duplicate id "${dup}"`);
  const main = root.querySelector('main');
  const h1 = main ? main.querySelectorAll('h1').length : 0;
  if (h1 !== 1) issues.push(`main must have exactly one h1 (found ${h1})`);
  const skip = root.querySelector('a.skip-link');
  if (skip?.getAttribute('href') !== '#main-content' || !document.getElementById('main-content')) issues.push('skip link must target #main-content');
  return issues;
}

async function open(path: string, as?: 'user@example.com' | 'admin@example.com') {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: true, adminAuditUi: true, notificationsUi: true, jobSearchAdvancedUi: true, applicationsUi: true, companyConsoleUi: true }),
    { initialEntries: [as ? '/login' : path] });
  const view = render(<RouterProvider router={router} />);
  if (as) {
    fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: as } });
    fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await screen.findByRole('link', { name: as === 'admin@example.com' ? '운영 관리자' : '일반 사용자' });
    // 로그인 후 기본 계정 화면으로의 이동이 완료되기 전 다음 navigate가 덮어써지지 않도록 한다.
    await screen.findByRole('heading', { name: '내 계정' });
    await act(() => router.navigate(path));
  }
  await screen.findByRole('heading', { level: 1 }, { timeout: 4000 });
  // 비동기 목록이 끝날 때까지 기다림(로딩 상태도 규칙을 지켜야 하므로 둘 다 점검)
  await waitFor(() => {
    if (document.querySelector('[aria-busy="true"]')) throw new Error('still loading');
  }, { timeout: 4000 }).catch(() => undefined);
  return view;
}

const PUBLIC = ['/', '/login', '/job-roles', '/job-postings', '/system-status', '/no-such-page'];
const SEEKER = ['/account', '/account/privacy', '/me/target-roles', '/me/career-history', '/me/bookmarks', '/me/skills',
  '/me/documents', '/recommendations', '/market-trends', '/admin/audit-events' /* 403 화면 */,
  '/me/notifications', '/me/notification-settings' /* T97, Mock 플래그 */, '/me/applications' /* T103 */, '/company' /* T124 */];
const ADMIN = ['/admin/moderation', '/admin/audit-events', '/admin/ai-usage'];

describe('accessibility rules on every main screen', () => {
  it.each(PUBLIC)('public %s', async (path) => {
    const { container } = await open(path);
    expect(audit(container)).toEqual([]);
  });

  it.each(SEEKER)('job seeker %s', async (path) => {
    const { container } = await open(path, 'user@example.com');
    expect(audit(container)).toEqual([]);
  });

  it.each(ADMIN)('admin %s', async (path) => {
    const { container } = await open(path, 'admin@example.com');
    expect(audit(container)).toEqual([]);
  });

  it('the forbidden screen is announced as a heading, not only colour', async () => {
    await open('/admin/ai-usage', 'user@example.com');
    expect(screen.getByRole('heading', { level: 1, name: '접근 권한이 없습니다' })).toBeInTheDocument();
  });
});

describe('keyboard and announcements', () => {
  it('login works with the keyboard only and the error is announced (role=alert)', async () => {
    const router = createMemoryRouter(buildRoutes({ adminModerationUi: false }), { initialEntries: ['/login'] });
    render(<RouterProvider router={router} />);
    const email = await screen.findByLabelText(/^이메일/);
    email.focus();
    fireEvent.change(email, { target: { value: 'user@example.com' } });
    const password = screen.getByLabelText(/^비밀번호/);
    fireEvent.change(password, { target: { value: 'wrong-password-123' } });
    fireEvent.submit(password.closest('form')!);   // Enter 키 제출과 같은 경로
    const alert = await screen.findByRole('alert');
    expect(alert.textContent?.trim()).not.toBe('');
    expect(alert.textContent).not.toContain('wrong-password-123');
  });

  it('modal: focus moves in, Tab cycles, Escape closes and focus returns to the trigger', async () => {
    function Harness() {
      const [openDialog, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>열기</button>
          {openDialog && (
            <ConfirmDialog title="확인" confirmLabel="진행" pending={false} onConfirm={() => setOpen(false)} onClose={() => setOpen(false)}>
              <label>사유<select defaultValue=""><option value="">선택</option></select></label>
            </ConfirmDialog>
          )}
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: '열기' });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole('dialog', { name: '확인' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(document.activeElement).toBe(screen.getByLabelText('사유'));
    const confirm = screen.getByRole('button', { name: '진행' });
    confirm.focus();
    fireEvent.keyDown(confirm, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByLabelText('사유'));
    fireEvent.keyDown(screen.getByLabelText('사유'), { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(confirm);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it('interactive controls are native buttons/links (Enter·Space work without custom handlers)', async () => {
    const { container } = await open('/job-postings');
    const fake = [...container.querySelectorAll('div[onclick], span[onclick], [role=button]:not(button)')];
    expect(fake).toEqual([]);
  });
});

// ---------------------------------------------------------------- colour contrast of design tokens (WCAG 2.x)
const CSS = readFileSync(resolve(cwd(), 'src/styles/global.css'), 'utf8');
const token = (name: string) => CSS.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))![1]!;
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
export const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

describe('colour contrast (normal text needs 4.5:1)', () => {
  it.each([
    ['color-text', 'color-bg'], ['color-text', 'color-surface'], ['color-text-muted', 'color-bg'],
    ['color-text-muted', 'color-surface'], ['color-primary', 'color-surface'], ['color-danger', 'color-surface'],
    ['color-warning', 'color-surface'], ['color-success', 'color-surface'], ['color-danger', 'color-bg'],
  ])('%s on %s', (fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5);
  });

  it('white text on the primary button', () => {
    expect(contrast('#ffffff', token('color-primary'))).toBeGreaterThanOrEqual(4.5);
  });

  it('the contrast helper matches the WCAG reference values', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 1);
    expect(contrast('#767676', '#ffffff')).toBeCloseTo(4.54, 1);
  });
});

describe('the audit itself catches violations (self-check)', () => {
  it('flags unlabeled controls, nameless buttons, missing alt, positive tabindex, duplicate ids and h1 count', () => {
    const { container } = render(
      <div>
        <a className="skip-link" href="#nowhere">본문</a>
        <main><h2>no h1</h2>
          <input name="q" /><button type="button" /><img src="x.png" />
          <span role="button">fake</span><a href="/x" tabIndex={3} /><p id="dup" /><p id="dup" />
        </main>
      </div>,
    );
    const issues = audit(container).join('\n');
    for (const expected of ['unlabeled control', 'button without accessible name', 'img without alt',
      'role=button not focusable', 'positive tabindex', 'duplicate id "dup"', 'exactly one h1', 'link without accessible name',
      'skip link']) {
      expect(issues).toContain(expected);
    }
  });
});
