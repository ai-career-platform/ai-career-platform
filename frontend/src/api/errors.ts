/** API 호출 실패(HTTP 4xx/5xx 또는 네트워크 오류). status 0 = 네트워크 오류 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(status: number, path: string, message?: string) {
    super(message ?? `API ${path} failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
  }
}
