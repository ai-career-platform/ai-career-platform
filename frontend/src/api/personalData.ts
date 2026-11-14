/**
 * 내 데이터 반출 요청 (T143 화면). 정책: docs/privacy/T141_DATA_SUBJECT_REQUEST_POLICY.md — **PROPOSED, openapi.yaml 에 없음**.
 * 서버(T142)는 `PERSONAL_DATA_REQUESTS_API=true` 일 때만 경로가 생기고(기본 꺼짐), 저장소는 migration 0006(PostgreSQL)입니다.
 * 반출 요청·다운로드는 10분 안 비밀번호 재확인이 필요하고, 다운로드 링크는 1회·10분, 묶음은 완료 후 24시간만 보관됩니다.
 */
import type { HttpClient } from './http';

export type RequestType = 'export' | 'erasure' | 'access' | 'rectification';
export type RequestStatus = 'pending_verification' | 'received' | 'in_progress' | 'completed' | 'failed'
  | 'rejected' | 'cancelled' | 'expired' | 'closed';

export type DataRequest = {
  request_id: string; request_type: RequestType; status: RequestStatus; created_at: string; updated_at: string;
  completed_at?: string | null; expires_at?: string | null; size_bytes?: number | null; reason_code?: string | null;
  attempts?: number; source: 'T142' | 'T31';
};
export type Reauth = { reauth_token: string; expires_at: string };
export type DownloadLink = { token: string; expires_at: string; uses: 1; notice: string };

export const TYPE_LABELS: Record<RequestType, string> = {
  export: '데이터 내보내기', erasure: '회원 탈퇴(삭제)', access: '열람', rectification: '정정',
};
export const STATUS_LABELS: Record<RequestStatus, string> = {
  pending_verification: '본인 확인 대기', received: '처리 대기', in_progress: '처리 중', completed: '완료 · 내려받기 가능',
  failed: '처리 실패', rejected: '반려', cancelled: '취소됨', expired: '만료됨', closed: '종결',
};
export const REASON_LABELS: Record<string, string> = {
  export_too_large: '데이터가 너무 커서 한 번에 만들 수 없습니다. 담당자가 나누어 처리합니다.',
  dependency_unavailable: '일시적인 오류로 만들지 못했습니다. 자동으로 다시 시도합니다(최대 3회).',
  storage_unavailable: '저장소 오류로 만들지 못했습니다. 자동으로 다시 시도합니다(최대 3회).',
  internal_error: '처리 중 오류가 발생했습니다.',
};
/** T141 반출에 포함하지 않는 항목(사람이 읽는 이름). 서버는 열 이름 기준으로 어떤 깊이에서든 제거합니다. */
export const EXCLUDED_LABELS = ['비밀번호(암호화 값 포함)', '로그인 세션·토큰', '접속 IP 기록', '파일 저장 위치(내부 키)',
  'AI 사용량 내부 기록'] as const;
export const INCLUDED_LABELS = ['계정·프로필', '경력·프로젝트·보유 기술·희망 직무', '업로드 문서 정보', '동의 기록',
  '북마크·이용 기록·추천 피드백', '분석·추천 결과', '탈퇴 요청 기록'] as const;
export const DOWNLOAD_TTL_HOURS = 24;
export const REAUTH_MINUTES = 10;

export interface PersonalDataService {
  list(signal?: AbortSignal): Promise<DataRequest[]>;
  reauth(password: string): Promise<Reauth>;
  createExport(reauthToken: string): Promise<DataRequest>;
  cancelExport(requestId: string): Promise<DataRequest>;
  downloadLink(requestId: string, reauthToken: string): Promise<DownloadLink>;
  download(token: string): Promise<Blob>;
}

export const T142_BASE_PATH = '/v1/me/data-requests';
/** 재인증 토큰 헤더(T142). 토큰은 메모리(화면 상태)에만 두고 URL·저장소에 남기지 않습니다. */
export const REAUTH_HEADER = 'X-Reauth-Token';

/**
 * 실제 API 어댑터(T142). 로그인 토큰이 붙은 HttpClient 를 씁니다.
 * - 재인증 토큰은 `X-Reauth-Token` 헤더로만 보냅니다.
 * - 다운로드 토큰은 URL 에 넣지 않고 POST 본문으로 보냅니다(접근 로그·Referer 노출 방지). 응답은 Blob.
 */
export function createHttpPersonalDataService(http: HttpClient): PersonalDataService {
  const exportPath = (id: string) => `${T142_BASE_PATH}/exports/${encodeURIComponent(id)}`;
  return {
    async list(signal) {
      const page = await http.request<{ items: DataRequest[] }>(T142_BASE_PATH, { signal });
      return page.items;
    },
    reauth: (password) => http.request<Reauth>(`${T142_BASE_PATH}/reauth`, { method: 'POST', body: { password } }),
    createExport: (reauthToken) => http.request<DataRequest>(`${T142_BASE_PATH}/exports`, {
      method: 'POST', headers: { [REAUTH_HEADER]: reauthToken } }),
    cancelExport: (requestId) => http.request<DataRequest>(`${exportPath(requestId)}/cancel`, { method: 'POST' }),
    downloadLink: (requestId, reauthToken) => http.request<DownloadLink>(`${exportPath(requestId)}/download-link`, {
      method: 'POST', headers: { [REAUTH_HEADER]: reauthToken } }),
    download: (token) => http.request<Blob>(`${T142_BASE_PATH}/download`, {
      method: 'POST', body: { token }, responseType: 'blob' }),
  };
}
