/** 기업 콘솔 오류 안내 (T124). 서버(T123)는 409 를 `CONFLICT` 하나로 주므로 화면이 맥락별 문구를 고릅니다. */
import { ApiError } from '../api/errors';

export function explain(error: unknown, context: 'role' | 'remove' | 'invite' | 'resend' | 'revoke' | 'register'): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 403) return context === 'invite' || context === 'resend'
      ? '이 작업은 운영 확인이 끝난 조직의 기업 관리자만 할 수 있습니다.' : '이 작업은 기업 관리자만 할 수 있습니다.';
    if (error.status === 404) return '조직이나 대상을 찾을 수 없거나 접근 권한이 없습니다.';
    if (error.status === 422) return '입력값을 확인해 주세요.';
    if (error.status === 409) {
      if (context === 'role' || context === 'remove') return '마지막 기업 관리자는 내리거나 제외할 수 없습니다. 또는 다른 곳에서 먼저 바뀌었습니다.';
      if (context === 'invite') return '이미 초대했거나 이미 멤버인 이메일입니다.';
      if (context === 'resend') return '대기 중인 초대가 아니거나 재전송 횟수를 모두 썼습니다.';
      return '현재 상태에서는 처리할 수 없습니다.';
    }
  }
  return '처리하지 못했습니다.';
}
