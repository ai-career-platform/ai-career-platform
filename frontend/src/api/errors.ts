/**
 * API 호출 실패(HTTP 4xx/5xx, 네트워크 오류, 또는 성공 상태지만 JSON 이 아닌 응답). status 0 = 네트워크 오류.
 * JSON 이 아닌 성공 응답은 실제 HTTP status 를 그대로 두고 code 를 INVALID_RESPONSE_CODE 로 둡니다.
 */
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

/** 성공 상태(2xx)인데 본문이 JSON 이 아닐 때의 클라이언트 측 code. Backend 카탈로그 코드가 아닙니다. */
export const INVALID_RESPONSE_CODE = 'INVALID_RESPONSE';

/** Backend request_id.py 의 안전 형식과 같습니다. 이 형식이 아니면 화면에 표시하지 않습니다. */
const SAFE_REQUEST_ID = /^[A-Za-z0-9._-]{8,64}$/;

/**
 * 오류 화면에 보여 줄 문의용 요청 번호(E2E-006 D-2). 응답의 X-Request-ID 를 그대로 쓰고,
 * 없거나 형식이 다르면 undefined — 값을 만들어 내지 않습니다.
 */
export function displayRequestId(error: unknown): string | undefined {
  const id = error instanceof ApiError ? error.requestId?.trim() : undefined;
  return id && SAFE_REQUEST_ID.test(id) ? id : undefined;
}
