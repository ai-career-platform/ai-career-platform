/** T50 개인 문서 API (T49 `/api/v1/documents`, docs/api/openapi.yaml Document·DocumentPage). */
import { ApiError, isAbortError } from './client';
import type { ApiRequestOptions } from './client';

export type DocumentKind = 'resume' | 'portfolio' | 'career_guide';
export type UploadKind = 'resume' | 'portfolio';
export type DocumentStatus = 'uploaded' | 'scanning' | 'ready' | 'rejected' | 'deleting';

/** Backend `Document`. 저장 키·체크섬·소유자 ID는 응답에 없습니다. */
export interface UserDocument {
  document_id: string;
  kind: DocumentKind;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  created_at: string;
}

export interface DocumentPage {
  items: UserDocument[];
  next_cursor: string | null;
}

/** useAuth().request 와 같은 모양. 토큰은 이 함수 안에서만 붙습니다. */
export type AuthedRequest = <T>(path: string, options?: ApiRequestOptions) => Promise<T>;

export const MAX_FILE_BYTES = 10 * 1024 * 1024; // T49 MAX_FILE_BYTES (10 MiB)
export const PDF_MIME = 'application/pdf';
export const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
export const ACCEPT = `.pdf,.docx,${PDF_MIME},${DOCX_MIME}`;
export const PAGE_SIZE = 20;

export const kindNames: Record<DocumentKind, string> = {
  resume: '이력서', portfolio: '포트폴리오', career_guide: '커리어 가이드',
};

export const statusNames: Record<DocumentStatus, string> = {
  uploaded: '확인 대기', scanning: '확인 대기', ready: '다운로드 가능', rejected: '사용 불가', deleting: '삭제 처리 중',
};

/** 서버 상태가 아직 바뀔 수 있는 문서 (재조회 대상) */
export const isPending = (status: DocumentStatus) => status === 'uploaded' || status === 'scanning' || status === 'deleting';

/** 브라우저 accept 속성만 믿지 않고 확장자·크기를 다시 확인합니다. 실제 내용 검증은 T49 서버가 합니다. */
export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!name.endsWith('.pdf') && !name.endsWith('.docx')) return 'PDF(.pdf) 또는 DOCX(.docx) 파일만 올릴 수 있습니다.';
  if (file.size <= 0) return '빈 파일은 올릴 수 없습니다.';
  if (file.size > MAX_FILE_BYTES) return '파일은 10MB 이하만 올릴 수 있습니다.';
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function listDocuments(request: AuthedRequest, cursor?: string | null) {
  const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (cursor) query.set('cursor', cursor);
  return request<DocumentPage>(`/v1/documents?${query.toString()}`);
}

export function getDocument(request: AuthedRequest, documentId: string) {
  return request<UserDocument>(`/v1/documents/${encodeURIComponent(documentId)}`);
}

export function uploadDocument(request: AuthedRequest, file: File, kind: UploadKind, signal?: AbortSignal) {
  const form = new FormData();
  form.append('kind', kind);
  form.append('file', file, file.name);
  return request<UserDocument>('/v1/documents', { method: 'POST', body: form, signal });
}

export function deleteDocument(request: AuthedRequest, documentId: string) {
  return request<UserDocument>(`/v1/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' });
}

/** 인증 요청으로 Blob 을 받아 임시 Object URL 로 저장하고 바로 해제합니다. */
export async function downloadDocument(request: AuthedRequest, doc: UserDocument, target: Document = document) {
  const blob = await request<Blob>(`/v1/documents/${encodeURIComponent(doc.document_id)}/file`, { responseType: 'blob' });
  const url = URL.createObjectURL(blob);
  try {
    const link = target.createElement('a');
    link.href = url;
    link.download = doc.original_filename;
    link.rel = 'noopener';
    target.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // 클릭으로 다운로드가 시작된 뒤 해제합니다(메모리·URL 재사용 방지).
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/** ApiError 를 화면 문구로 바꿉니다. 응답 원문·토큰·내부 정보는 표시하지 않습니다. */
export function documentErrorMessage(error: unknown, action: 'list' | 'upload' | 'download' | 'delete'): string {
  if (isAbortError(error)) return '업로드를 취소했습니다.';
  if (!(error instanceof ApiError)) return '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.';
  switch (error.status) {
    case 0: return '네트워크 연결을 확인한 뒤 다시 시도해 주세요.';
    case 401: return '로그인이 필요합니다. 다시 로그인해 주세요.';
    case 404: return '문서를 찾을 수 없습니다. 이미 삭제되었거나 접근할 수 없는 문서입니다.';
    case 409: return action === 'download' ? '아직 다운로드할 수 없는 문서입니다. 확인이 끝난 뒤 다시 시도해 주세요.'
      : '현재 상태에서는 처리할 수 없습니다.';
    case 413: return '파일은 10MB 이하만 올릴 수 있습니다.';
    case 415: return 'PDF 또는 DOCX 파일만 올릴 수 있습니다.';
    case 422: return '입력값 또는 파일 형식을 확인해 주세요.';
    case 503: return '문서 서비스를 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.';
    default: return error.userMessage ?? '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.';
  }
}
