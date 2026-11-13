import { useState } from 'react';
import { env } from '../config/env';
import { googleStartHref } from './google';
import { useGoogleAvailable } from './useGoogleAvailable';

/**
 * "Google로 계속하기" — Backend 시작 주소로 전체 페이지 이동합니다(SPA 안에서 fetch 하지 않음).
 * 한 번 누르면 이동 중으로 바뀌고 이후 클릭은 무시해 Google 인가 요청이 여러 번 생기지 않게 합니다.
 * 기능이 꺼진 서버(404)·확인 실패에서는 버튼을 그리지 않습니다.
 */
export function GoogleLoginButton({ returnPath }: { returnPath: string }) {
  const available = useGoogleAvailable();
  const [starting, setStarting] = useState(false);
  if (!available) return null;
  return (
    <a
      href={googleStartHref(env.apiBaseUrl, returnPath)}
      className="ui-button ui-button--outline login-google"
      aria-disabled={starting || undefined}
      onClick={(event) => {
        if (starting) {
          event.preventDefault();
          return;
        }
        setStarting(true);
      }}
    >
      {starting ? 'Google로 이동 중…' : 'Google로 계속하기'}
    </a>
  );
}
