import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './errors';
import { CSRF_HEADER, createHttpClient } from './http';
import {
  MAX_FILE_BYTES, documentErrorMessage, documentsApi, isAbortError, saveDocument, validateFile,
} from './documents';
import type { UserDocument } from './documents';
import { mockHttp } from '../test/api';
import { FOREIGN_DOCUMENT_ID, resetDocumentMocks, settleDocumentMocks } from '../mocks/documents';

const api = () => documentsApi(mockHttp('mock-access-user@example.com'));

function sized(name: string, size: number, type = '') {
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

beforeEach(() => resetDocumentMocks());
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('http.ts extensions for T50 (real transport path)', () => {
  it('sends FormData without a manual Content-Type, keeps CSRF and bearer headers', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"ok":true}', { status: 202 }));
    const http = createHttpClient({ baseUrl: '/api', fetch: fetchImpl, getToken: () => 't' });
    await documentsApi(http).upload(sized('a.pdf', 3), 'resume');
    const [url, init] = fetchImpl.mock.calls[0]!;
    const headers = init?.headers as Record<string, string>;
    expect(url).toBe('/api/v1/documents');
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init!.body as FormData).get('kind')).toBe('resume');
    expect(headers['Content-Type']).toBeUndefined();
    expect(headers[CSRF_HEADER]).toBe('1');
    expect(headers.Authorization).toBe('Bearer t');
  });

  it('keeps JSON requests unchanged', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 200 }));
    await createHttpClient({ baseUrl: '/api', fetch: fetchImpl }).request('/v1/x', { method: 'POST', body: { a: 1 } });
    const init = fetchImpl.mock.calls[0]![1]!;
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init.body).toBe('{"a":1}');
  });

  it('returns a Blob for responseType blob and builds list query', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async (url) =>
      String(url).endsWith('/file') ? new Response('pdf', { status: 200 })
        : new Response('{"items":[],"next_cursor":null}', { status: 200 }));
    const docs = documentsApi(createHttpClient({ baseUrl: '/api', fetch: fetchImpl }));
    const blob = await docs.file('d 1');
    expect(blob).toBeInstanceOf(Blob);
    expect(await blob.text()).toBe('pdf');
    expect(fetchImpl.mock.calls[0]![0]).toBe('/api/v1/documents/d%201/file');
    await docs.list('c-2');
    expect(fetchImpl.mock.calls[1]![0]).toBe('/api/v1/documents?limit=20&cursor=c-2');
  });

  it('abort is an AbortError, distinct from network errors (status 0)', async () => {
    const ctrl = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(() => {
      ctrl.abort();
      return Promise.reject(new DOMException('aborted', 'AbortError'));
    });
    const aborted = await documentsApi(createHttpClient({ baseUrl: '/api', fetch: fetchImpl }))
      .upload(sized('a.pdf', 1), 'resume', ctrl.signal).catch((e: unknown) => e);
    expect(isAbortError(aborted)).toBe(true);
    const network = await documentsApi(createHttpClient({ baseUrl: '/api',
      fetch: vi.fn<typeof fetch>().mockRejectedValue(new TypeError('x')) })).list().catch((e: unknown) => e);
    expect(network).toBeInstanceOf(ApiError);
    expect(isAbortError(network)).toBe(false);
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
    expect(documentErrorMessage(new DOMException('a', 'AbortError'), 'upload')).toBe('업로드를 취소했습니다.');
  });
});

describe('document mock lifecycle through mockFetch (synthetic, not Backend evidence)', () => {
  it('upload -> scanning -> ready, blob download, delete -> deleting -> 404', async () => {
    const docs = api();
    const created = await docs.upload(sized('이력서.pdf', 2048, 'application/pdf'), 'resume');
    expect(created.status).toBe('scanning');
    expect(Object.keys(created).sort()).toEqual(['created_at', 'document_id', 'kind', 'mime_type', 'original_filename',
      'size_bytes', 'status']);
    await expect(docs.file(created.document_id)).rejects.toMatchObject({ status: 409, code: 'DOCUMENT_NOT_READY' });
    settleDocumentMocks();
    expect((await docs.get(created.document_id)).status).toBe('ready');
    expect(await (await docs.file(created.document_id)).text()).toBe('synthetic mock file');
    expect((await docs.list()).items).toHaveLength(1);
    expect((await docs.remove(created.document_id)).status).toBe('deleting');
    expect((await docs.remove(created.document_id)).status).toBe('deleting'); // repeat allowed
    settleDocumentMocks();
    await expect(docs.get(created.document_id)).rejects.toMatchObject({ status: 404 });
  });

  it('other user documents are 404; anonymous is 401; server rejects bad type/size', async () => {
    await expect(api().get(FOREIGN_DOCUMENT_ID)).rejects.toMatchObject({ status: 404 });
    await expect(documentsApi(mockHttp(null)).list()).rejects.toMatchObject({ status: 401 });
    await expect(api().upload(sized('a.exe', 10), 'resume')).rejects.toMatchObject({ status: 415 });
    const big = new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'big.pdf', { type: 'application/pdf' });
    await expect(api().upload(big, 'resume')).rejects.toMatchObject({ status: 413 });
  });

  it('download creates a temporary object URL and revokes it', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    const create = vi.fn<(blob: Blob) => string>(() => 'blob:mock-url');
    const revoke = vi.fn<(url: string) => void>();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const doc: UserDocument = { document_id: '1', kind: 'resume', original_filename: 'a.pdf', mime_type: 'application/pdf',
      size_bytes: 1, status: 'ready', created_at: '2026-11-01T00:00:00Z' };
    const fake = { ...api(), file: vi.fn<(id: string) => Promise<Blob>>().mockResolvedValue(new Blob(['x'])) };
    await saveDocument(fake, doc);
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a[download]')).toBeNull();
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledWith('blob:mock-url');
  });
});
