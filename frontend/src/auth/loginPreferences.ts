/**
 * 로그인 화면 설정(아이디 저장·자동 로그인). 비밀번호와 토큰은 저장하지 않고,
 * 시크릿 창 등에서 저장소가 막혀 있어도 로그인 자체는 동작해야 하므로 모든 접근을 try/catch 로 감쌉니다.
 */
const SAVED_EMAIL = 'login.savedEmail';
const AUTO_LOGIN = 'login.autoLogin'; // localStorage: 브라우저를 닫아도 유지
const SESSION_ALIVE = 'login.sessionAlive'; // sessionStorage: 같은 브라우저 세션 안에서만 유지

const safely = <T,>(fn: () => T, fallback: T): T => {
  try {
    return fn();
  } catch {
    return fallback;
  }
};

export const getSavedEmail = () => safely(() => localStorage.getItem(SAVED_EMAIL) ?? '', '');

export const saveEmail = (email: string | null) =>
  safely(() => (email ? localStorage.setItem(SAVED_EMAIL, email) : localStorage.removeItem(SAVED_EMAIL)), undefined);

/** 로그인 성공 직후 호출. 자동 로그인을 끄면 이 브라우저 세션 동안만 로그인을 유지합니다. */
export const rememberSession = (autoLogin: boolean) =>
  safely(() => {
    if (autoLogin) localStorage.setItem(AUTO_LOGIN, '1');
    else localStorage.removeItem(AUTO_LOGIN);
    sessionStorage.setItem(SESSION_ALIVE, '1');
  }, undefined);

/**
 * 새로고침 복구(refresh 쿠키) 뒤에 세션을 이어가도 되는지.
 * shortcut: 서버 refresh 쿠키는 14일짜리 고정이라 "자동 로그인 끔"은 화면에서만 지킨다(브라우저를 닫으면 로그아웃 처리),
 * 서버가 로그인 요청의 유지 여부(세션 쿠키)를 받게 되면 서버 쪽으로 옮긴다.
 */
export const shouldKeepSession = () =>
  safely(() => localStorage.getItem(AUTO_LOGIN) === '1' || sessionStorage.getItem(SESSION_ALIVE) === '1', true);

export const forgetSession = () =>
  safely(() => {
    localStorage.removeItem(AUTO_LOGIN);
    sessionStorage.removeItem(SESSION_ALIVE);
  }, undefined);
