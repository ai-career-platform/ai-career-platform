/**
 * T50 synthetic document mock. Simulates T49 state transitions in memory only.
 * File contents are never stored; downloads return a fixed synthetic placeholder.
 * Mock success is not Backend/PostgreSQL evidence.
 */
import { ApiError } from '../api/errors';
import type { UserDocument } from '../api/documents';
import type { MockRequest } from './handlers';

const MAX_FILE_BYTES = 10 * 1024 * 1024;
/** 업로드 후 이 시간이 지나면 다음 조회에서 scanning -> ready/rejected (개발 화면용) */
export const MOCK_SCAN_MS = 3000;

interface Entry { doc: UserDocument; settleAt: number }
const states = new Map<string, Entry[]>();
/** 다른 사용자의 문서 ID (404 확인용 합성 값) */
export const FOREIGN_DOCUMENT_ID = '00000000-0000-4000-8000-0000000000f0';

export function resetDocumentMocks() { states.clear(); }

/** 테스트용: 대기 중 상태를 즉시 다음 단계로 진행시킵니다. */
export function settleDocumentMocks() {
  for (const entries of states.values()) for (const e of entries) e.settleAt = 0;
}

/** 테스트·개발용 합성 문서 추가 */
export function seedDocumentMock(userKey: string, doc: Partial<UserDocument> & Pick<UserDocument, 'original_filename'>) {
  const full: UserDocument = {
    document_id: crypto.randomUUID(), kind: 'resume', mime_type: 'application/pdf', size_bytes: 2048,
    status: 'ready', created_at: '2026-11-01T00:00:00Z', ...doc,
  };
  userDocs(userKey).push({ doc: full, settleAt: Number.POSITIVE_INFINITY });
  return full;
}

function userDocs(key: string) {
  let docs = states.get(key);
  if (!docs) { docs = []; states.set(key, docs); }
  return docs;
}

function advance(entries: Entry[]) {
  const now = Date.now();
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const e = entries[i];
    if (!e || now < e.settleAt) continue;
    if (e.doc.status === 'scanning') {
      e.doc.status = /reject/i.test(e.doc.original_filename) ? 'rejected' : 'ready';
      e.settleAt = Number.POSITIVE_INFINITY;
    } else if (e.doc.status === 'deleting') {
      entries.splice(i, 1);
    }
  }
}

const fail = (status: number, path: string, code: string): never => { throw new ApiError(status, path, undefined, code); };

export function resolveDocumentsMock(rawPath: string, request: MockRequest, userKey: string): unknown {
  const [path = rawPath, queryString = ''] = rawPath.split('?');
  const entries = userDocs(userKey);
  advance(entries);
  if (path === '/v1/documents') {
    if (request.method === 'GET') {
      const query = new URLSearchParams(queryString);
      const limit = Number(query.get('limit') ?? 20);
      const offset = Number(query.get('cursor') ?? 0);
      const sorted = [...entries].map(e => e.doc).sort((a, b) => b.created_at.localeCompare(a.created_at)
        || b.document_id.localeCompare(a.document_id));
      const items = sorted.slice(offset, offset + limit);
      return { items, next_cursor: offset + limit < sorted.length ? String(offset + limit) : null };
    }
    if (request.method === 'POST') {
      const form = request.body;
      if (!(form instanceof FormData)) return fail(422, path, 'VALIDATION_FAILED');
      const file = form.get('file');
      const kind = form.get('kind');
      if (!(file instanceof File) || (kind !== 'resume' && kind !== 'portfolio')) return fail(422, path, 'VALIDATION_FAILED');
      const name = file.name.toLowerCase();
      if (!name.endsWith('.pdf') && !name.endsWith('.docx')) return fail(415, path, 'UNSUPPORTED_FILE_TYPE');
      if (file.size > MAX_FILE_BYTES) return fail(413, path, 'FILE_TOO_LARGE');
      const doc: UserDocument = {
        document_id: crypto.randomUUID(), kind, original_filename: file.name,
        mime_type: name.endsWith('.pdf') ? 'application/pdf'
          : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        size_bytes: file.size, status: 'scanning', created_at: new Date().toISOString(),
      };
      entries.push({ doc, settleAt: Date.now() + MOCK_SCAN_MS }); // metadata only, content discarded
      return doc;
    }
  }
  const match = /^\/v1\/documents\/([^/]+)(\/file)?$/.exec(path);
  if (!match) return null;
  const id = decodeURIComponent(match[1] ?? '');
  const entry = entries.find(e => e.doc.document_id === id);
  if (!entry) return fail(404, path, 'NOT_FOUND'); // unknown or another user's document
  if (match[2]) {
    if (request.method !== 'GET') return null;
    if (entry.doc.status !== 'ready') return fail(409, path, 'DOCUMENT_NOT_READY');
    return new Blob(['synthetic mock file'], { type: entry.doc.mime_type });
  }
  if (request.method === 'GET') return entry.doc;
  if (request.method === 'DELETE') {
    if (entry.doc.status !== 'deleting') { // repeated DELETE is accepted (T49), timer is not extended
      entry.doc.status = 'deleting';
      entry.settleAt = Date.now() + MOCK_SCAN_MS;
    }
    return entry.doc;
  }
  return null;
}
