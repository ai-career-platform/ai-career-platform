/**
 * T50 개인 문서 API (T49 `/api/v1/documents`). 경로와 타입은 이 파일에만 둡니다.
 * 화면은 useApi().documents 로 씁니다. 타입은 T06 계약(schema.gen)의 Document·DocumentPage 입니다.
 */
import { ApiError } from './errors';
import type { HttpClient } from './http';
import type { Schemas } from './schema';

/** 저장 키·체크섬·소유자 ID는 계약상 응답에 없습니다. */
export type UserDocument = Schemas['Document'];
export type DocumentPage = Schemas['DocumentPage'];
export type DocumentKind = UserDocument['kind'];
export type DocumentStatus = UserDocument['status'];
export type UploadKind = 'resume' | 'portfolio';

export const MAX_FILE_BYTES = 10 * 1024 * 1024; // T49 MAX_FILE_BYTES (10 MiB)
export const PDF_MIME = 'application/pdf';
export const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
export const ACCEPT = `.pdf,.docx,${PDF_MIME},${DOCX_MIME}`;
export const PAGE_SIZE = 20;

const id = (value: string) => encodeURIComponent(value);

export const documentsApi = (http: HttpClient) => ({
  list: (cursor?: string | null, signal?: AbortSignal) =>
    http.request<DocumentPage>('/v1/documents', { query: { limit: PAGE_SIZE, cursor }, signal }),
  get: (documentId: string, signal?: AbortSignal) =>
    http.request<UserDocument>(`/v1/documents/${id(documentId)}`, { signal }),
  upload: (file: File, kind: UploadKind, signal?: AbortSignal) => {
    const form = new FormData();
    form.append('kind', kind);
    form.append('file', file, file.name);
    return http.request<UserDocument>('/v1/documents', { method: 'POST', body: form, signal });
  },
  file: (documentId: string) =>
    http.request<Blob>(`/v1/documents/${id(documentId)}/file`, { responseType: 'blob' }),
  remove: (documentId: string) =>
    http.request<UserDocument>(`/v1/documents/${id(documentId)}`, { method: 'DELETE' }),
});

export type DocumentsApi = ReturnType<typeof documentsApi>;

export const kindNames: Record<DocumentKind, string> = {
  resume: '이력서', portfolio: '포트폴리오', career_guide: '커리어 가이드',
};

export const statusNames: Record<DocumentStatus, string> = {
  uploaded: '확인 대기', scanning: '확인 대기', ready: '다운로드 가능', rejected: '사용 불가', deleting: '삭제 처리 중',
};

/** 서버 상태가 아직 바뀔 수 있는 문서 (재조회 대상) */
export const isPending = (status: DocumentStatus) => status === 'uploaded' || status === 'scanning' || status === 'deleting';

/** 사용자가 취소한 요청(http.ts 는 AbortError 를 그대로 던짐). 취소된 요청은 성공으로 다루지 않습니다. */
export const isAbortError = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';

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

/** 인증 요청으로 Blob 을 받아 임시 Object URL 로 저장하고, 클릭 직후 해제합니다. */
export async function saveDocument(api: DocumentsApi, doc: UserDocument, target: Document = document) {
  const blob = await api.file(doc.document_id);
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
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/** 오류를 화면 문구로 바꿉니다. 응답 원문·토큰·내부 정보는 표시하지 않습니다. */
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
