/**
 * T82 운영 콘텐츠 검수 화면의 도메인 타입과 서비스 인터페이스.
 *
 * - 타입은 T80 구현 계약(docs/admin/MODERATION_IMPLEMENTATION_CONTRACT.md §1~§4)의 **제안 DTO**를 따릅니다.
 *   T81 API·OpenAPI가 없으므로 schema.gen.ts 에서 가져오지 않습니다. T81 병합 후 생성 타입으로 바꿉니다.
 * - 화면은 ModerationService 인터페이스만 씁니다. 지금은 메모리 Mock(mocks/moderation.ts)만 연결되고,
 *   T81 이후 moderationHttp.ts 를 연결합니다.
 * - availableActions 는 버튼 표시용(UX)입니다. 권한·상태 판단의 기준은 서버(T81)이며, Mock Adapter도
 *   같은 규칙으로 따로 거부합니다.
 */
import { ApiError } from './errors';

export const MODERATION_STATUSES = ['PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'APPEALED', 'CLOSED'] as const;
export type ModerationStatus = (typeof MODERATION_STATUSES)[number];

export const TARGET_TYPES = [
  'job_posting', 'company', 'shared_document', 'document_analysis', 'retrieval_run', 'agent_run',
  'match_evaluation', 'recommendation_run',
] as const;
export type TargetType = (typeof TARGET_TYPES)[number];

export type ReviewTrigger = 'PRE_PUBLISH' | 'REPORT' | 'EXPIRY' | 'SOURCE_CHANGE';
export type Priority = 1 | 2 | 3;
export type CloseReason = 'WITHDRAWN' | 'TARGET_DELETED' | 'SUPERSEDED';

export const REASON_CODES = [
  'RIGHTS_UNCLEAR', 'INACCURATE', 'PERSONAL_DATA', 'HARMFUL', 'DISCRIMINATORY', 'DUPLICATE', 'EXPIRED', 'MALWARE',
  'OTHER',
] as const;
export type ReasonCode = (typeof REASON_CODES)[number];
export const NOTE_MAX_LENGTH = 500;

export interface ModerationCaseSummary {
  case_id: string;
  target_type: TargetType;
  target_id: string;
  /** 목록에 보여도 되는 대상 요약(공개 제목 등). 비공개 원문·신고자 정보는 넣지 않습니다. (PROPOSED 필드) */
  target_summary: string;
  trigger: ReviewTrigger;
  status: ModerationStatus;
  priority: Priority;
  assignee_id: string | null;
  due_at: string;
  flags: string[];
  report_count: number;
  version: number;
}

export interface ModerationCaseEvent {
  event_id: string;
  event: 'SUBMIT' | 'ASSIGN' | 'REASSIGN' | 'RELEASE' | 'RELEASE_APPEAL' | 'APPROVE' | 'REJECT' | 'APPEAL'
    | 'WITHDRAW_APPEAL' | 'CLOSE';
  from_status: ModerationStatus | null;
  to_status: ModerationStatus;
  /** null 이면 system */
  actor_id: string | null;
  reason_code: string | null;
  occurred_at: string;
}

/** 상세. 관리자 내부 메모(reviewer_note)는 화면 응답에 넣지 않습니다. */
export interface ModerationCaseDetail extends ModerationCaseSummary {
  content_owner_id: string | null;
  submitted_by: string | null;
  first_decider_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  reason_code: ReasonCode | null;
  appeal_count: 0 | 1;
  close_reason: CloseReason | null;
  created_at: string;
  events: ModerationCaseEvent[];
}

export interface ModerationListQuery {
  status?: ModerationStatus;
  target_type?: TargetType;
  priority?: Priority;
}

export type Decision =
  | { decision: 'APPROVE' }
  | { decision: 'REJECT'; reason_code: ReasonCode; note?: string };

/** 화면이 쓰는 유일한 데이터 경로. 실패는 ApiError(status, code)로 던집니다. */
export interface ModerationService {
  list(query: ModerationListQuery, signal?: AbortSignal): Promise<{ items: ModerationCaseSummary[]; next_cursor: null }>;
  get(caseId: string, signal?: AbortSignal): Promise<ModerationCaseDetail>;
  assign(caseId: string, body: { version: number }): Promise<ModerationCaseDetail>;
  decide(caseId: string, body: { version: number } & Decision): Promise<ModerationCaseDetail>;
}

export const OPEN_STATUSES: readonly ModerationStatus[] = ['PENDING', 'IN_REVIEW', 'APPEALED'];

export type Allowed = { allowed: true } | { allowed: false; reason: string };

const deny = (reason: string): Allowed => ({ allowed: false, reason });
const ok: Allowed = { allowed: true };

function closedReason(c: ModerationCaseDetail): Allowed | null {
  if (c.status === 'APPROVED' || c.status === 'REJECTED') return deny('이미 결정된 검수 건입니다.');
  if (c.status === 'CLOSED') return deny('종료된 검수 건입니다.');
  return null;
}

function selfReview(c: ModerationCaseDetail, viewerId: string): Allowed | null {
  if (viewerId === c.content_owner_id || viewerId === c.submitted_by) return deny('자기 콘텐츠는 검수할 수 없습니다.');
  if (c.appeal_count === 1 && viewerId === c.first_decider_id) {
    return deny('이의제기 재검토는 최초 결정자가 아닌 관리자가 맡아야 합니다.');
  }
  return null;
}

/** 버튼 활성화용 판정 (T80 상태 모델 T02·T06·T07·T09). 서버 판단을 대신하지 않습니다. */
export function availableActions(c: ModerationCaseDetail, viewerId: string | null | undefined): {
  assign: Allowed; decide: Allowed;
} {
  if (!viewerId) return { assign: deny('로그인 정보를 확인할 수 없습니다.'), decide: deny('로그인 정보를 확인할 수 없습니다.') };
  const closed = closedReason(c);
  if (closed) return { assign: closed, decide: closed };
  const self = selfReview(c, viewerId);
  const assign = c.status === 'IN_REVIEW' ? deny('이미 담당자가 있습니다.') : self ?? ok;
  let decide: Allowed;
  if (c.status !== 'IN_REVIEW') decide = deny('담당을 시작한 뒤 결정할 수 있습니다.');
  else if (c.assignee_id !== viewerId) decide = deny('담당자만 승인·반려할 수 있습니다.');
  else decide = self ?? ok;
  return { assign, decide };
}

/** 반려 입력 검사 (정책 §5.1). 화면과 Mock 이 같은 규칙을 씁니다. */
export function rejectInputError(reason: string, note: string): string | null {
  if (!(REASON_CODES as readonly string[]).includes(reason)) return '반려 사유를 선택해 주세요.';
  if (reason === 'OTHER' && !note.trim()) return '기타(OTHER) 사유는 설명을 입력해야 합니다.';
  if (note.length > NOTE_MAX_LENGTH) return `설명은 ${NOTE_MAX_LENGTH}자 이하로 입력해 주세요.`;
  return null;
}

/** API 오류를 화면 문구로 바꿉니다. 409 는 최신 내용을 다시 불러오라고 안내합니다. */
export function moderationErrorMessage(error: unknown): { message: string; reload: boolean } {
  if (error instanceof ApiError) {
    if (error.status === 401) return { message: '로그인이 필요합니다. 다시 로그인해 주세요.', reload: false };
    if (error.status === 403) return { message: '이 검수 건을 처리할 권한이 없습니다.', reload: false };
    if (error.status === 404) return { message: '검수 건을 찾을 수 없습니다.', reload: false };
    if (error.status === 409 && error.code === 'APPROVAL_CLOSED') {
      return { message: '이미 처리되었거나 종료된 검수 건입니다. 최신 내용을 다시 불러오세요.', reload: true };
    }
    if (error.status === 409) {
      return { message: '다른 관리자가 먼저 이 건을 바꿨습니다. 최신 내용을 다시 불러온 뒤 처리해 주세요.', reload: true };
    }
    if (error.status === 422) return { message: '입력값을 확인해 주세요. 반려 사유와 설명이 필요합니다.', reload: false };
  }
  return { message: '처리하지 못했습니다. 잠시 후 다시 시도해 주세요.', reload: false };
}

export const STATUS_LABELS: Record<ModerationStatus, string> = {
  PENDING: '대기', IN_REVIEW: '검수 중', APPROVED: '승인', REJECTED: '반려', APPEALED: '이의제기 재검토 대기',
  CLOSED: '종료',
};
export const TARGET_TYPE_LABELS: Record<TargetType, string> = {
  job_posting: '채용공고', company: '기업', shared_document: '공용 자료', document_analysis: 'AI 문서 분석',
  retrieval_run: 'AI 질의응답', agent_run: 'AI 작업', match_evaluation: 'AI 적합도', recommendation_run: 'AI 추천',
};
export const TRIGGER_LABELS: Record<ReviewTrigger, string> = {
  PRE_PUBLISH: '게시 전 검수', REPORT: '신고', EXPIRY: '만료 재검수', SOURCE_CHANGE: '출처 변경 재검수',
};
export const PRIORITY_LABELS: Record<Priority, string> = { 1: 'P1 긴급', 2: 'P2 신고', 3: 'P3 게시 전' };
export const REASON_LABELS: Record<ReasonCode, string> = {
  RIGHTS_UNCLEAR: '권리·출처 불명확', INACCURATE: '부정확·허위 정보', PERSONAL_DATA: '개인정보 포함', HARMFUL: '유해',
  DISCRIMINATORY: '차별', DUPLICATE: '중복', EXPIRED: '만료', MALWARE: '악성 파일', OTHER: '기타 (설명 필수)',
};
export const CLOSE_REASON_LABELS: Record<CloseReason, string> = {
  WITHDRAWN: '요청 철회', TARGET_DELETED: '대상 삭제', SUPERSEDED: '새 건으로 대체',
};
export const FLAG_LABELS: Record<string, string> = {
  PII_PATTERN: '개인정보 패턴 의심', DUPLICATE_SUSPECT: '중복 의심', BANNED_TERM: '금칙어 포함',
};
export const EVENT_LABELS: Record<ModerationCaseEvent['event'], string> = {
  SUBMIT: '접수', ASSIGN: '담당 시작', REASSIGN: '담당 변경', RELEASE: '담당 해제', RELEASE_APPEAL: '재검토 담당 해제',
  APPROVE: '승인', REJECT: '반려', APPEAL: '이의제기', WITHDRAW_APPEAL: '이의제기 철회', CLOSE: '종료',
};
