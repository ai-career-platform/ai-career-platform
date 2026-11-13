import { Link, Navigate, useSearchParams } from 'react-router';
import { env } from '../config/env';
import { googleStartHref, nextAppPath } from '../auth/google';
import { useAuth } from '../auth/useAuth';
import './LoginPage.css';

/**
 * #328 Google 인증 완료(재방문 사용자) 경로 `/auth/google/done?next=…`.
 * Backend 가 refresh 쿠키를 이미 심었으므로 AuthProvider 의 기존 refresh 복원 흐름을 그대로 기다립니다.
 * (AuthProvider 가 첫 refresh 전에 세션 유지 표시를 해 둡니다 — AuthContext.arrivedFromGoogle)
 * 복원되면 허용된 내부 경로(next)로만 이동하고, 실패하면 다시 시도할 수 있게 안내합니다.
 */
export function GoogleDonePage() {
  const { state } = useAuth();
  const [params] = useSearchParams();
  const target = nextAppPath(params.get('next'));

  if (state.status === 'authenticated') return <Navigate to={target} replace />;
  if (state.status === 'loading') {
    return (
      <section className="login-page" aria-busy="true">
        <p role="status">Google 로그인을 마무리하는 중…</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="google-done-title" className="login-page">
      <div className="login-card">
        <h1 id="google-done-title" className="login-title">로그인을 완료하지 못했습니다</h1>
        <p role="alert" className="login-error">
          로그인 정보를 확인하지 못했습니다. 브라우저 쿠키가 차단되어 있지 않은지 확인한 뒤 다시 시도해 주세요.
        </p>
        <a className="ui-button ui-button--outline login-google" href={googleStartHref(env.apiBaseUrl, target)}>
          Google로 다시 시도
        </a>
        <p className="login-signup"><Link to="/login">로그인 화면으로</Link></p>
      </div>
    </section>
  );
}
