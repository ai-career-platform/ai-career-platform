/** API 호출 실패(HTTP 4xx/5xx 또는 네트워크 오류). status 0 = 네트워크 오류 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  /** 오류 응답의 code (예: INVALID_CREDENTIALS). 없으면 undefined */
  readonly code?: string;
  /** 오류 응답의 message — Backend 카탈로그의 사용자용 문구(API_CONTRACT §1.4). 화면에 그대로 표시 가능 */
  readonly userMessage?: string;

  constructor(status: number, path: string, message?: string, code?: string, userMessage?: string) {
    super(message ?? `API ${path} failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.code = code;
    this.userMessage = userMessage;
  }
}
