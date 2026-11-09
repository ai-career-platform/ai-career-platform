/** 422 필드 오류 한 건 (problem+json errors[]) */
export interface FieldError {
  field: string;
  code: string;
}

/** API 호출 실패(HTTP 4xx/5xx 또는 네트워크 오류). status 0 = 네트워크 오류 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  /** problem+json 의 code (예: INVALID_CREDENTIALS). 없으면 undefined */
  readonly code?: string;
  readonly errors: FieldError[];

  constructor(status: number, path: string, message?: string, code?: string, errors: FieldError[] = []) {
    super(message ?? `API ${path} failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.code = code;
    this.errors = errors;
  }
}
