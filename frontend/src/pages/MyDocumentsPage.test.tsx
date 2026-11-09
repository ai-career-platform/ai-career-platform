import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import { RequireAuth } from '../auth/RequireAuth';
import { ApiError } from '../api/errors';
import { mockHttp, type RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { MAX_FILE_BYTES } from '../api/documents';
import { resetDocumentMocks, seedDocumentMock, settleDocumentMocks } from '../mocks/documents';
import { MyDocumentsPage } from './MyDocumentsPage';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

const TOKEN = 'mock-access-user@example.com';
const USER = 'user@example.com';
type Req = RequestFn;
const user = mockHttp(TOKEN);
const viaMock: Req = (path, options) => user.request(path, options);

function show({ anonymous = false, custom }: { anonymous?: boolean; custom?: (next: Req) => Req } = {}) {
  const request = vi.fn<Req>(custom ? custom(viaMock) : viaMock);
  const value: AuthContextValue = {
    state: anonymous ? { status: 'anonymous' } : { status: 'authenticated', token: TOKEN,
      user: { email: USER, displayName: '합성 사용자', roles: ['job_seeker'] } },
    login: vi.fn<AuthContextValue['login']>().mockResolvedValue(undefined),
    logout: vi.fn<AuthContextValue['logout']>().mockResolvedValue(undefined),
  };
  render(<AuthContext.Provider value={value}><WithApi request={request}><MemoryRouter initialEntries={['/me/documents']}>
    <Routes><Route element={<Outlet />}><Route element={<RequireAuth />}>
      <Route path="/me/documents" element={<MyDocumentsPage />} />
    </Route><Route path="/login" element={<h1>로그인 필요</h1>} /></Route></Routes>
  </MemoryRouter></WithApi></AuthContext.Provider>);
  return request;
}

function file(name: string, size = 2048, type = 'application/pdf') {
  const f = new File([new Uint8Array(size)], name, { type });
  return f;
}
const input = () => screen.getByLabelText('파일 선택 (PDF 또는 DOCX)');
const choose = (f: File) => fireEvent.change(input(), { target: { files: [f] } });
const retryUpload = () => screen.getByRole('button', { name: '다시 시도' });
const posts = (request: ReturnType<typeof show>) =>
  request.mock.calls.filter(([path, o]) => path === '/v1/documents' && o?.method === 'POST');
const item = (name: string) => screen.getByRole('article', { name });

let setItem: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  resetDocumentMocks();
  setItem = vi.spyOn(Storage.prototype, 'setItem');
  Object.assign(URL, { createObjectURL: vi.fn<(blob: Blob) => string>(() => 'blob:synthetic'), revokeObjectURL: vi.fn<(url: string) => void>() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

describe('T50 my documents (Mock only, not Backend evidence)', () => {
  it('redirects anonymous users through RequireAuth without calling the API', async () => {
    const request = show({ anonymous: true });
    expect(await screen.findByRole('heading', { name: '로그인 필요' })).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });

  it('shows loading then empty state with privacy notice and limits', async () => {
    show();
    expect(screen.getByText('문서 목록을 불러오는 중')).toBeInTheDocument();
    expect(await screen.findByText('등록한 문서가 없습니다')).toBeInTheDocument();
    expect(screen.getByText(/개인정보가 포함될 수 있습니다/)).toBeInTheDocument();
    expect(screen.getByText(/최대 10.0 MB/)).toBeInTheDocument();
    expect(input()).toHaveAttribute('accept', expect.stringContaining('.pdf'));
    expect(screen.getByRole('combobox', { name: '문서 종류' })).toHaveValue('resume');
    expect(screen.getByRole('button', { name: '파일 선택' })).toBeEnabled();
  });

  it.each([['이력서.pdf', 'application/pdf'], ['포트폴리오.DOCX', '']])('accepts %s and shows name and size', async (name, type) => {
    show(); await screen.findByText('등록한 문서가 없습니다');
    choose(file(name, 2048, type));
    await screen.findByRole('article', { name });
    expect(screen.getByText(name)).toBeInTheDocument();
    expect(screen.getByText(/2.0 KB/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '파일 선택' })).toBeEnabled();
  });

  it('rejects wrong extensions and files over 10MiB before sending', async () => {
    const request = show(); await screen.findByText('등록한 문서가 없습니다');
    choose(file('resume.pdf.exe', 10, 'application/pdf'));
    expect(screen.getByRole('alert')).toHaveTextContent('PDF(.pdf) 또는 DOCX(.docx)');
    expect(screen.getByRole('button', { name: '파일 선택' })).toBeEnabled();
    choose(file('big.pdf', MAX_FILE_BYTES + 1));
    expect(screen.getByRole('alert')).toHaveTextContent('10MB 이하');
    expect(input()).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('button', { name: '파일 선택' })).toBeEnabled();
    expect(posts(request)).toHaveLength(0);
  });

  it('shows uploading state, blocks duplicate submit, then lists the new scanning document', async () => {
    const request = show(); await screen.findByText('등록한 문서가 없습니다');
    fireEvent.change(screen.getByRole('combobox', { name: '문서 종류' }), { target: { value: 'portfolio' } });
    choose(file('포트폴리오.pdf'));
    fireEvent.drop(screen.getByTestId('document-dropzone'), { dataTransfer: { files: [file('중복.pdf')] } });
    expect(screen.getByRole('button', { name: '파일 선택' })).toBeDisabled();
    expect(screen.getByText(/업로드 중입니다/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument(); // no fake progress percentage
    expect(screen.getByRole('combobox', { name: '문서 종류' })).toBeDisabled();
    expect(await screen.findByText('업로드를 접수했습니다. 파일을 확인하는 중입니다.')).toBeInTheDocument();
    expect(posts(request)).toHaveLength(1);
    const form = posts(request)[0]![1]!.body as FormData;
    expect(form.get('kind')).toBe('portfolio');
    const row = item('포트폴리오.pdf');
    expect(within(row).getByText('확인 대기')).toBeInTheDocument();
    expect(within(row).getByText('포트폴리오')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: '포트폴리오.pdf 다운로드' })).toBeDisabled();
    expect(input()).toHaveValue('');
  });

  it('cancels an in-flight upload, never reports success, reloads the list to show server state, can retry', async () => {
    const request = show(); await screen.findByText('등록한 문서가 없습니다');
    choose(file('이력서.pdf'));
    fireEvent.click(screen.getByRole('button', { name: '업로드 취소' }));
    expect(await screen.findByText(/업로드를 취소했습니다/)).toBeInTheDocument();
    expect(screen.queryByText('업로드를 접수했습니다. 파일을 확인하는 중입니다.')).not.toBeInTheDocument();
    await waitFor(() => expect(request.mock.calls.filter(([p]) => p.startsWith('/v1/documents?'))).toHaveLength(2));
    // The synthetic server had already received the request: the reloaded list shows it (deletable), not a fake success.
    expect(await screen.findByRole('article', { name: '이력서.pdf' })).toBeInTheDocument();
    expect(retryUpload()).toBeEnabled(); // file kept for retry
    fireEvent.click(retryUpload());
    expect(await screen.findByText('업로드를 접수했습니다. 파일을 확인하는 중입니다.')).toBeInTheDocument();
    expect(screen.getAllByRole('article', { name: '이력서.pdf' })).toHaveLength(2);
  });

  it('uploads a dropped file immediately with the selected kind', async () => {
    const request = show(); await screen.findByText('등록한 문서가 없습니다');
    fireEvent.change(screen.getByRole('combobox', { name: '문서 종류' }), { target: { value: 'portfolio' } });
    const zone = screen.getByTestId('document-dropzone');
    fireEvent.dragOver(zone);
    expect(zone).toHaveClass('documents-drop--active');
    fireEvent.drop(zone, { dataTransfer: { files: [file('드롭.pdf')] } });
    expect(zone).not.toHaveClass('documents-drop--active');
    await screen.findByRole('article', { name: '드롭.pdf' });
    expect(posts(request)).toHaveLength(1);
    expect((posts(request)[0]![1]!.body as FormData).get('kind')).toBe('portfolio');
  });

  it('rejects invalid drops and keeps file selection as a keyboard alternative', async () => {
    const request = show(); await screen.findByText('등록한 문서가 없습니다');
    fireEvent.drop(screen.getByTestId('document-dropzone'), { dataTransfer: { files: [file('wrong.exe')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('PDF(.pdf) 또는 DOCX(.docx)');
    expect(posts(request)).toHaveLength(0);
    const click = vi.spyOn(input(), 'click');
    fireEvent.click(screen.getByRole('button', { name: '파일 선택' }));
    expect(click).toHaveBeenCalledOnce();
  });

  it('only ready documents can be downloaded; rejected cannot; object URL is revoked', async () => {
    seedDocumentMock(USER, { original_filename: '완료.pdf', status: 'ready', created_at: '2026-11-02T00:00:00Z' });
    seedDocumentMock(USER, { original_filename: '거부.pdf', status: 'rejected' });
    show(); await screen.findByRole('article', { name: '완료.pdf' });
    const rejected = item('거부.pdf');
    expect(within(rejected).getByText('사용 불가')).toBeInTheDocument();
    expect(within(rejected).getByRole('button', { name: '거부.pdf 다운로드' })).toBeDisabled();
    fireEvent.click(within(item('완료.pdf')).getByRole('button', { name: '완료.pdf 다운로드' }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:synthetic'));
  });

  it('scanning becomes ready after a status refresh', async () => {
    show(); await screen.findByText('등록한 문서가 없습니다');
    choose(file('검사.pdf'));
    await screen.findByRole('article', { name: '검사.pdf' });
    settleDocumentMocks();
    fireEvent.click(screen.getByRole('button', { name: '상태 새로고침' }));
    expect(await within(item('검사.pdf')).findByText('다운로드 가능')).toBeInTheDocument();
    expect(within(item('검사.pdf')).getByRole('button', { name: '검사.pdf 다운로드' })).toBeEnabled();
  });

  it('removes a document when download returns 404 (not owned or already gone)', async () => {
    seedDocumentMock(USER, { original_filename: '타인.pdf', status: 'ready' });
    show({ custom: next => (path, o) => path.endsWith('/file')
      ? Promise.reject(new ApiError(404, path, undefined, 'NOT_FOUND')) : next(path, o) });
    fireEvent.click(within(await screen.findByRole('article', { name: '타인.pdf' })).getByRole('button', { name: '타인.pdf 다운로드' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('찾을 수 없습니다');
    expect(screen.queryByRole('article', { name: '타인.pdf' })).not.toBeInTheDocument();
  });

  it('shows list error with retry, and API/network upload errors as alerts', async () => {
    let failList = true;
    let uploadError: ApiError = new ApiError(415, '/v1/documents', undefined, 'UNSUPPORTED_FILE_TYPE');
    show({ custom: next => (path, o) => {
      if (path.startsWith('/v1/documents?') && failList) return Promise.reject(new ApiError(503, path));
      if (path === '/v1/documents' && o?.method === 'POST') return Promise.reject(uploadError);
      return next(path, o);
    } });
    expect(await screen.findByText('문서 목록을 불러오지 못했습니다')).toBeInTheDocument();
    failList = false;
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('등록한 문서가 없습니다')).toBeInTheDocument();
    choose(file('a.pdf'));
    expect(await screen.findByRole('alert')).toHaveTextContent('PDF 또는 DOCX 파일만');
    uploadError = new ApiError(0, '/v1/documents', 'Network error');
    fireEvent.click(retryUpload());
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('네트워크 연결'));
    uploadError = new ApiError(413, '/v1/documents');
    fireEvent.click(retryUpload());
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('10MB 이하'));
  });

  it('delete: cancel makes no call; confirm shows deleting and blocks download; completion removes it', async () => {
    seedDocumentMock(USER, { original_filename: '삭제.pdf', status: 'ready' });
    const request = show();
    const remove = within(await screen.findByRole('article', { name: '삭제.pdf' })).getByRole('button', { name: '삭제.pdf 삭제' });
    fireEvent.click(remove);
    const dialog = screen.getByRole('dialog', { name: '문서 삭제 확인' });
    fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(request.mock.calls.filter(([, o]) => o?.method === 'DELETE')).toHaveLength(0);

    fireEvent.click(remove);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '삭제' }));
    expect(await screen.findByText(/삭제를 요청했습니다/)).toBeInTheDocument();
    const row = item('삭제.pdf');
    expect(within(row).getByText('삭제 처리 중', { selector: '.documents-status' })).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: '삭제.pdf 다운로드' })).toBeDisabled();
    expect(within(row).getByRole('button', { name: '삭제.pdf 삭제' })).toBeDisabled();
    expect(request.mock.calls.filter(([, o]) => o?.method === 'DELETE')).toHaveLength(1);

    settleDocumentMocks();
    fireEvent.click(screen.getByRole('button', { name: '상태 새로고침' }));
    expect(await screen.findByText('문서 삭제가 완료되었습니다.')).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: '삭제.pdf' })).not.toBeInTheDocument();
  });

  it('delete network error keeps the dialog open with an alert; 404 removes the row', async () => {
    seedDocumentMock(USER, { original_filename: '네트워크.pdf', status: 'ready' });
    let failure: ApiError = new ApiError(0, '/x');
    show({ custom: next => (path, o) => o?.method === 'DELETE' ? Promise.reject(failure) : next(path, o) });
    fireEvent.click(within(await screen.findByRole('article', { name: '네트워크.pdf' })).getByRole('button', { name: '네트워크.pdf 삭제' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '삭제' }));
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('네트워크');
    expect(within(item('네트워크.pdf')).queryByText('삭제 처리 중', { selector: '.documents-status' })).toBeNull();
    failure = new ApiError(404, '/x');
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '삭제' }));
    await waitFor(() => expect(screen.queryByRole('article', { name: '네트워크.pdf' })).not.toBeInTheDocument());
  });

  it('dialog traps focus, closes with Escape and returns focus to the trigger', async () => {
    seedDocumentMock(USER, { original_filename: '키보드.pdf', status: 'ready' });
    show();
    const trigger = within(await screen.findByRole('article', { name: '키보드.pdf' })).getByRole('button', { name: '키보드.pdf 삭제' });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog');
    const [cancel, confirm] = within(dialog).getAllByRole('button');
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('never exposes tokens or storage keys and never writes browser storage', async () => {
    seedDocumentMock(USER, { original_filename: '노출검사.pdf', status: 'ready' });
    const log = vi.spyOn(console, 'log');
    show(); await screen.findByRole('article', { name: '노출검사.pdf' });
    choose(file('업로드.pdf'));
    await screen.findByRole('article', { name: '업로드.pdf' });
    await act(async () => { fireEvent.click(within(item('노출검사.pdf')).getByRole('button', { name: '노출검사.pdf 다운로드' })); });
    const text = document.body.textContent ?? '';
    expect(text).not.toContain(TOKEN);
    expect(text).not.toMatch(/storage_key|checksum|[0-9a-f]{64}/);
    expect(setItem).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
  });
});
