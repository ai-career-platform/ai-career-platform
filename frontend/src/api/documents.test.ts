import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiRequest, isAbortError } from './client';
import type { ApiRequestOptions } from './client';
import {
  MAX_FILE_BYTES, deleteDocument, documentErrorMessage, downloadDocument, getDocument, listDocuments,
  uploadDocument, validateFile,
} from './documents';
import type { UserDocument } from './documents';
import { FOREIGN_DOCUMENT_ID, resetDocumentMocks, settleDocumentMocks } from '../mocks/documents';

const TOKEN = 'mock-access-user@example.com';
const mockRequest = <T,>(path: string, options: ApiRequestOptions = {}) =>
  apiRequest<T>(path, { ...options, token: TOKEN, mockEnabled: true });

function sized(name: string, size: number, type = '') {
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

beforeEach(() => resetDocumentMocks());
afterEach(() => vi.restoreAllMocks());

describe('apiRequest extensions for T50 (real fetch path)', () => {
  it('sends FormData without a manual Content-Type and keeps the bearer token', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"ok":true}', { status: 202 }));
    const form = new FormData();
    form.append('kind', 'resume');
    await apiRequest('/v1/documents', { method: 'POST', body: form, token: 't', fetchImpl, mockEnabled: false });
    const [url, init] = fetchImpl.mock.calls[0]!;
    const headers = init?.headers as Record<string, string>;
    expect(url).toBe('/api/v1/documents');
    expect(init?.body).toBe(form);
    expect(headers['Content-Type']).toBeUndefined();
    expect(headers.Authorization).toBe('Bearer t');
  });

  it('keeps JSON requests unchanged', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 200 }));
    await apiRequest('/v1/x', { method: 'POST', body: { a: 1 }, fetchImpl, mockEnabled: false });
    const init = fetchImpl.mock.calls[0]![1]!;
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init.body).toBe('{"a":1}');
  });

  it('returns a Blob for responseType blob', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('pdf', { status: 200 }));
    const blob = await apiRequest<Blob>('/v1/documents/1/file', { responseType: 'blob', fetchImpl, mockEnabled: false });
    expect(blob).toBeInstanceOf(Blob);
    expect(await blob.text()).toBe('pdf');
  });

  it('maps an aborted fetch to ApiError ABORTED, distinct from network errors', async () => {
    const ctrl = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(() => {
      ctrl.abort();
      return Promise.reject(new DOMException('aborted', 'AbortError'));
    });
    const error = await apiRequest('/v1/documents', { method: 'POST', body: new FormData(), signal: ctrl.signal,
      fetchImpl, mockEnabled: false }).catch(e => e);
    expect(isAbortError(error)).toBe(true);
    const network = await apiRequest('/v1/documents', { fetchImpl: vi.fn<typeof fetch>().mockRejectedValue(new TypeError('x')),
      mockEnabled: false }).catch(e => e);
    expect(network).toBeInstanceOf(ApiError);
    expect(isAbortError(network)).toBe(false);
    expect((network as ApiError).status).toBe(0);
  });
});

describe('client-side file validation (server T49 still validates content)', () => {
  it.each(['이력서.pdf', 'Portfolio.DOCX', 'a.b.pdf'])('accepts %s', name => {
    expect(validateFile(sized(name, 1024))).toBeNull();
  });
  it.each(['resume.exe', 'resume.pdf.exe', 'resume.doc', 'resume', 'shell.php'])('rejects %s', name => {
    expect(validateFile(sized(name, 1024))).toMatch(/PDF/);
  });
  it('rejects empty and over 10MiB, accepts exactly 10MiB', () => {
    expect(validateFile(sized('a.pdf', 0))).toMatch(/빈 파일/);
    expect(validateFile(sized('a.pdf', MAX_FILE_BYTES + 1))).toMatch(/10MB/);
    expect(validateFile(sized('a.pdf', MAX_FILE_BYTES))).toBeNull();
  });
});

describe('document error messages', () => {
  it.each([
    [0, '네트워크'], [401, '로그인'], [404, '찾을 수 없습니다'], [413, '10MB'], [415, 'PDF 또는 DOCX'],
    [422, '입력값'], [503, '잠시 사용할 수 없습니다'],
  ])('status %i', (status, text) => {
    expect(documentErrorMessage(new ApiError(status, '/v1/documents'), 'upload')).toContain(text);
  });
  it('409 differs for download', () => {
    expect(documentErrorMessage(new ApiError(409, '/x'), 'download')).toContain('아직 다운로드할 수 없는');
  });
  it('abort is reported as cancellation, never success', () => {
    expect(documentErrorMessage(new ApiError(0, '/x', 'a', 'ABORTED'), 'upload')).toBe('업로드를 취소했습니다.');
  });
});

describe('document mock lifecycle (synthetic, not Backend evidence)', () => {
  it('upload -> scanning -> ready, download blob, delete -> deleting -> 404', async () => {
    const created = await uploadDocument(mockRequest, sized('이력서.pdf', 2048, 'application/pdf'), 'resume');
    expect(created.status).toBe('scanning');
    expect(Object.keys(created).sort()).toEqual(['created_at', 'document_id', 'kind', 'mime_type', 'original_filename',
      'size_bytes', 'status']);
    await expect(downloadDocument(mockRequest, created)).rejects.toMatchObject({ status: 409 });
    settleDocumentMocks();
    const ready = await getDocument(mockRequest, created.document_id);
    expect(ready.status).toBe('ready');
    expect((await listDocuments(mockRequest)).items).toHaveLength(1);
    const deleting = await deleteDocument(mockRequest, created.document_id);
    expect(deleting.status).toBe('deleting');
    expect((await deleteDocument(mockRequest, created.document_id)).status).toBe('deleting'); // repeat allowed
    settleDocumentMocks();
    await expect(getDocument(mockRequest, created.document_id)).rejects.toMatchObject({ status: 404 });
  });

  it('other user documents are 404 and cancelled uploads are not stored', async () => {
    await expect(getDocument(mockRequest, FOREIGN_DOCUMENT_ID)).rejects.toMatchObject({ status: 404 });
    const ctrl = new AbortController();
    const pending = uploadDocument(mockRequest, sized('a.pdf', 10), 'resume', ctrl.signal);
    ctrl.abort();
    expect(isAbortError(await pending.catch(e => e))).toBe(true);
    expect((await listDocuments(mockRequest)).items).toEqual([]);
  });

  it('download creates a temporary object URL and revokes it', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    const create = vi.fn<(blob: Blob) => string>(() => 'blob:mock-url');
    const revoke = vi.fn<(url: string) => void>();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const doc: UserDocument = { document_id: '1', kind: 'resume', original_filename: 'a.pdf', mime_type: 'application/pdf',
      size_bytes: 1, status: 'ready', created_at: '2026-11-01T00:00:00Z' };
    const request = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>().mockResolvedValue(new Blob(['x'])) as unknown as typeof mockRequest;
    await downloadDocument(request, doc);
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a[download]')).toBeNull();
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledWith('blob:mock-url');
    vi.useRealTimers();
  });
});
