/**
 * T146 공통 화면 문구 표준(한국어 기본, 영어 대응표).
 *
 * - 현재 서비스 화면은 한국어만 노출합니다(`<html lang="ko">`). 영어 문구는 **표준 대응표**이며
 *   언어 전환 기능은 승인 전이라 켜지 않았습니다(PROPOSED).
 * - 화면마다 같은 상황에 다른 말을 쓰지 않도록 상태 문구(로딩·빈 화면·오류·재시도·권한)를 여기서 고릅니다.
 * - 기존 화면 문구를 한꺼번에 바꾸지 않습니다. 새 화면과 수정하는 화면부터 이 표를 씁니다.
 * - `{name}` 자리표시자는 `t()`가 그대로 바꿔 넣습니다. HTML은 넣지 않습니다(React가 문자열로만 출력).
 */
import { DEFAULT_LOCALE, type Locale } from './format';

export const MESSAGES = {
  ko: {
    'state.loading': '불러오는 중입니다…',
    'state.empty': '표시할 항목이 없습니다.',
    'state.error': '정보를 불러오지 못했습니다.',
    'state.errorHint': '로그인 상태와 네트워크 연결을 확인해 주세요.',
    'action.retry': '다시 시도',
    'action.cancel': '취소',
    'action.save': '저장',
    'action.close': '닫기',
    'auth.required': '로그인이 필요합니다.',
    'auth.forbidden': '접근 권한이 없습니다',
    'form.required': '{name}을(를) 입력해 주세요.',
    'form.tooLong': '{name}은(는) {max}자 이하로 입력해 주세요.',
    'time.kst': '한국 시간',
    'mock.badge': 'Mock 데이터',
    'nav.skip': '본문으로 바로가기',
  },
  en: {
    'state.loading': 'Loading…',
    'state.empty': 'Nothing to show yet.',
    'state.error': 'We could not load this information.',
    'state.errorHint': 'Check that you are signed in and online.',
    'action.retry': 'Try again',
    'action.cancel': 'Cancel',
    'action.save': 'Save',
    'action.close': 'Close',
    'auth.required': 'Please sign in.',
    'auth.forbidden': 'You do not have access',
    'form.required': 'Enter {name}.',
    'form.tooLong': '{name} must be {max} characters or fewer.',
    'time.kst': 'Korea Standard Time',
    'mock.badge': 'Mock data',
    'nav.skip': 'Skip to main content',
  },
} as const satisfies Record<Locale, Record<string, string>>;

export type MessageKey = keyof (typeof MESSAGES)['ko'];

/** 문구 조회. 없는 키는 개발 실수이므로 키 이름을 그대로 돌려 화면에서 바로 보이게 합니다. */
export function t(key: MessageKey, params: Record<string, string | number> = {}, locale: Locale = DEFAULT_LOCALE): string {
  const template: string = MESSAGES[locale][key] ?? MESSAGES[DEFAULT_LOCALE][key] ?? key;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in params ? String(params[name]) : whole));
}
