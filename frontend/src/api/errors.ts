/** API 호출 실패(HTTP 4xx/5xx 또는 네트워크 오류). status 0 = 네트워크 오류 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  /** 오류 응답의 code (예: INVALID_CREDENTIALS). 없으면 undefined */
  readonly code?: string;
  /** 오류 응답의 message — Backend 카탈로그의 사용자용 문구(API_CONTRACT §1.4). 화면에 그대로 표시 가능 */
  readonly userMessage?: string;
  /** 응답 X-Request-ID — 오류 화면의 요청 번호, 감사 기록 조회 키 (FR-ADM-004) */
  readonly requestId?: string;
  /** 오류 응답의 헤더 (T156: 크롤러 관리자 명령 거부 사유 X-Crawler-Command-Reason). 네트워크 오류면 undefined */
  readonly headers?: Headers;

  constructor(status: number, path: string, message?: string, code?: string, userMessage?: string, requestId?: string,
    headers?: Headers) {
    super(message ?? `API ${path} failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.code = code;
    this.userMessage = userMessage;
    this.requestId = requestId;
    this.headers = headers;
  }
}
