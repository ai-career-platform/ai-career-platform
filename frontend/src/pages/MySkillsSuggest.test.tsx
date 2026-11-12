/**
 * T140 기술 자동완성 UX (VITE_SKILL_AUTOCOMPLETE=true). Mock 응답 기준 — 실제 API 증빙이 아닙니다.
 * 실제 API(T139 + PostgreSQL) 확인은 docs/testing/T140_VALIDATION_REPORT.md 의 로컬 브라우저 확인을 봅니다.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import { ApiError } from '../api/client';
import { mockHttp, type RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { resetSkillsMocks } from '../mocks/skills';
import { normalizeSkillTerm } from '../api/skills';
import { MySkillsPage } from './MySkillsPage';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, skillAutocomplete: true } }));

const viaMock: RequestFn = (path, options = {}) => mockHttp('mock-access-user@example.com').request(path, options);

function show(custom?: RequestFn) {
  const request = vi.fn<RequestFn>(custom ?? viaMock);
  const value: AuthContextValue = {
    state: { status: 'authenticated', token: 'mock-access-user@example.com',
      user: { email: 'user@example.com', displayName: '합성 사용자', roles: ['job_seeker'] } },
    login: vi.fn<AuthContextValue['login']>().mockResolvedValue(undefined),
    logout: vi.fn<AuthContextValue['logout']>().mockResolvedValue(undefined), signup: vi.fn<AuthContextValue['signup']>(),
  };
  render(<AuthContext.Provider value={value}><WithApi request={request}><MemoryRouter initialEntries={['/me/skills']}>
    <Routes><Route path="/me/skills" element={<MySkillsPage />} /></Routes>
  </MemoryRouter></WithApi></AuthContext.Provider>);
  return request;
}

const box = () => screen.findByRole('combobox', { name: '기술 검색' });
const rowNames = () => screen.queryAllByRole('listitem').filter(li => li.classList.contains('skills-row'))
  .map(li => li.querySelector('.skills-name')!.firstChild!.textContent);
const suggestCalls = (request: ReturnType<typeof show>) =>
  request.mock.calls.map(([path]) => path).filter(p => p.startsWith('/v1/skills'));

async function type(text: string) {
  const input = await box();
  fireEvent.change(input, { target: { value: text } });
  return input;
}

beforeEach(() => resetSkillsMocks());

describe('T140 기술 자동완성 (Mock)', () => {
  it('정규화 규칙은 T139 서버(T137)와 같다', () => {
    expect(normalizeSkillTerm('  Node . JS ')).toBe('nodejs');
    expect(normalizeSkillTerm('C++')).toBe('c++');
    expect(normalizeSkillTerm('C#')).toBe('c#');
    expect(normalizeSkillTerm('Ｐｙｔｈｏｎ')).toBe('python');
    expect(normalizeSkillTerm('리액트 네이티브')).toBe('리액트네이티브');
  });

  it('한글 동의어로 표준 기술을 찾아 Enter 로 추가하고 T139 경로를 부른다', async () => {
    const request = show();
    const input = await type('파이썬');
    const option = await screen.findByRole('option', { name: /Python/ });
    expect(option).toHaveTextContent('‘파이썬’로 찾음');
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(rowNames()).toEqual(['Python']));
    expect(suggestCalls(request).every(p => p.startsWith('/v1/skills/suggest?'))).toBe(true);
    expect(suggestCalls(request).at(-1)).toContain('q=%ED%8C%8C%EC%9D%B4%EC%8D%AC');
  });

  it('영문 줄임말·대소문자·한 음절 입력도 찾는다', async () => {
    show();
    const input = await type('K8S');
    expect(await screen.findByRole('option', { name: /Kubernetes/ })).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '도' } });
    expect(await screen.findByRole('option', { name: /Docker/ })).toHaveTextContent('‘도커’');
  });

  it('키보드: ↓↑ 로 이동(순환), aria-activedescendant 갱신, Esc 로 닫힘', async () => {
    show();
    const input = await type('py');
    const options = await screen.findAllByRole('option');
    expect(options.length).toBeGreaterThanOrEqual(3);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(input.getAttribute('aria-activedescendant')).toBe(options[0]!.id);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(input.getAttribute('aria-activedescendant')).toBe(options[1]!.id);
    expect(options[1]).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(input.getAttribute('aria-activedescendant')).toBe(options.at(-1)!.id);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('다의어(py)는 후보를 모두 보여 주고 자동으로 고르지 않는다', async () => {
    show();
    await type('py');
    const listbox = await screen.findByRole('listbox', { name: '기술 검색 결과' });
    const ambiguous = await within(listbox).findAllByText(/여러 기술 중 골라 주세요/);
    expect(ambiguous).toHaveLength(2);
    expect(rowNames()).toEqual([]);
  });

  it('한글 조합 중 Enter 는 무시하고, 조합이 끝난 뒤 Enter 로 추가한다', async () => {
    show();
    const input = await type('쿠버네티스');
    await screen.findByRole('option', { name: /Kubernetes/ });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(rowNames()).toEqual([]);
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(rowNames()).toEqual(['Kubernetes']));
  });

  it('이미 추가한 기술은 다른 표기로 찾아도 중복으로 추가되지 않는다', async () => {
    show();
    const input = await type('파이썬');
    fireEvent.click(await screen.findByRole('option', { name: /Python/ }));
    await waitFor(() => expect(rowNames()).toEqual(['Python']));
    fireEvent.change(input, { target: { value: 'python' } });
    const again = await screen.findByRole('option', { name: /Python/ });
    expect(again).toHaveAttribute('aria-disabled', 'true');
    expect(again).toHaveTextContent('추가됨');
    fireEvent.click(again);
    expect(await screen.findByText('Python은(는) 이미 추가한 기술입니다.')).toBeInTheDocument();
    expect(rowNames()).toEqual(['Python']);
  });

  it('등록할 수 없는 코드(skill_id 없음)는 고를 수 없다', async () => {
    show();
    const input = await type('러스트');
    const rust = await screen.findByRole('option', { name: /Rust/ });
    expect(rust).toHaveAttribute('aria-disabled', 'true');
    expect(rust).toHaveTextContent('아직 등록할 수 없는 기술');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(await screen.findByText(/아직 등록할 수 있는 기술 목록에 없습니다/)).toBeInTheDocument();
    expect(rowNames()).toEqual([]);
  });

  it('빈 결과·오류 상태를 보여 준다', async () => {
    show((path, options) => path.startsWith('/v1/skills/suggest?q=err')
      ? Promise.reject(new ApiError(503, '', undefined, 'DEPENDENCY_UNAVAILABLE')) : viaMock(path, options));
    const input = await type('없는기술이름');
    expect(await screen.findByText('검색 결과가 없습니다. 다른 이름으로 찾아보세요.')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'err' } });
    expect(await screen.findByText('검색하지 못했습니다. 잠시 후 다시 시도해 주세요.')).toBeInTheDocument();
  });

  it('빠르게 입력을 바꾸면 늦게 온 이전 응답은 화면을 덮어쓰지 않는다', async () => {
    const pending = new Map<string, (value: unknown) => void>();
    show((path, options) => {
      if (!path.startsWith('/v1/skills/suggest')) return viaMock(path, options);
      // 취소 신호를 무시하는 느린 서버를 흉내: 요청마다 수동으로 응답한다
      return new Promise(resolve => pending.set(new URLSearchParams(path.split('?')[1]).get('q')!, resolve));
    });
    const input = await type('자바');
    await waitFor(() => expect(pending.has('자바')).toBe(true));
    fireEvent.change(input, { target: { value: '타입' } });
    await waitFor(() => expect(pending.has('타입')).toBe(true));
    await act(async () => pending.get('타입')!({ items: [{ code: 'TYPESCRIPT', name: 'TypeScript', match_type: 'prefix',
      matched: '타입스크립트', skill_id: '00000000-0000-4000-8000-000000000006' }], next_cursor: null, alias_source: 'taxonomy' }));
    expect(await screen.findByRole('option', { name: /TypeScript/ })).toBeInTheDocument();
    await act(async () => pending.get('자바')!({ items: [{ code: 'JAVASCRIPT', name: 'JavaScript', match_type: 'prefix',
      matched: '자바스크립트', skill_id: '00000000-0000-4000-8000-000000000005' }], next_cursor: null, alias_source: 'taxonomy' }));
    expect(screen.queryByRole('option', { name: /JavaScript/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(1);
  });
});
