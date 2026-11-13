import { useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Link, Navigate, useNavigate } from 'react-router';
import { ApiError, publicHttp } from '../api/client';
import { useApi } from '../api/ApiContext';
import { policyNames } from '../api/privacy';
import type { ConsentPolicy } from '../api/privacy';
import { useQuery } from '../api/useQuery';
import { env } from '../config/env';
import { googleApi, googleStartHref } from '../auth/google';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { TextField } from '../components/TextField';
import './LoginPage.css';

const restartLink = (label = 'Google로 다시 시작') => (
  <a className="ui-button ui-button--outline login-google" href={googleStartHref(env.apiBaseUrl, '/')}>{label}</a>
);

/** 서버 응답 → 화면 안내. 비밀 정보나 내부 사유는 보여 주지 않습니다. */
function problemFor(error: unknown): ReactNode {
  if (error instanceof ApiError) {
    if (error.code === 'GOOGLE_SIGNUP_EXPIRED' || error.status === 401) {
      return <>가입 시간이 지났습니다(10분). Google 로그인부터 다시 시작해 주세요. {restartLink()}</>;
    }
    if (error.code === 'GOOGLE_NOT_ALLOWED') {
      return '이 Google 계정은 사용이 허용되지 않았습니다. 관리자에게 문의해 주세요.';
    }
    if (error.code === 'GOOGLE_EMAIL_CONFLICT' || error.status === 409) {
      return (
        <>
          이 이메일로 가입된 계정이 있습니다. Google 계정을 자동으로 연결하지 않으니 기존 비밀번호로{' '}
          <Link to="/login">로그인</Link>해 주세요.
        </>
      );
    }
    if (error.status === 422) return '필수 약관에 모두 동의했는지 확인해 주세요.';
    if (error.status === 429) return '요청이 많습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 0) return '서버에 연결할 수 없습니다. 네트워크를 확인한 뒤 다시 눌러 주세요.';
  }
  return '가입 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.';
}

/**
 * #328 Google 최초 가입(약관 동의) `/auth/google/signup`.
 * 이메일·이름은 서버가 확인한 가입 대기 정보(GET /auth/google/pending)만 보여 줍니다. 이메일·Google sub 는 보내지 않고,
 * 서버가 서명된 pending 쿠키로 신원을 확인합니다. 제출은 한 번만 진행되며(중복 클릭 무시) 최종 동의 검증은 서버가 합니다.
 */
export function GoogleSignupPage() {
  const { state, googleSignup } = useAuth();
  const api = useApi();
  const navigate = useNavigate();
  const pending = useQuery(['google-pending'], (signal) => googleApi(publicHttp).pending(signal));
  const policies = useQuery(['consent-policies'], (signal) => api.me.consents.policies(signal));
  const [error, setError] = useState<ReactNode>(null);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);

  if (state.status === 'authenticated') return <Navigate to="/" replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>, list: ConsentPolicy[]) {
    event.preventDefault();
    if (inFlight.current) return; // 중복 제출 방지(서버도 pending 1회 사용으로 막음)
    const form = new FormData(event.currentTarget);
    const missing = list.filter((p) => p.is_required && form.get(`consent-${p.policy_code}`) !== 'on');
    if (missing.length > 0) {
      setError(`필수 약관에 동의해 주세요: ${missing.map((p) => policyNames[p.policy_code] ?? p.policy_code).join(', ')}`);
      return;
    }
    const displayName = String(form.get('displayName') ?? '').trim();
    if (!displayName) {
      setError('이름을 입력해 주세요.');
      return;
    }
    inFlight.current = true;
    setError(null);
    setSubmitting(true);
    try {
      await googleSignup({
        display_name: displayName,
        consents: list.map((p) => ({
          policy_code: p.policy_code,
          policy_version: p.version,
          granted: form.get(`consent-${p.policy_code}`) === 'on',
        })),
      });
      navigate('/', { replace: true });
    } catch (e) {
      setError(problemFor(e));
      inFlight.current = false; // 네트워크 오류 등은 다시 시도할 수 있다
    } finally {
      setSubmitting(false);
    }
  }

  let body: ReactNode;
  if (pending.status === 'error') {
    body = <div role="alert" className="login-error">{problemFor(pending.error)}</div>;
  } else if (policies.status === 'error') {
    body = (
      <div role="alert" className="login-error">
        약관 정보를 불러오지 못했습니다.{' '}
        <Button variant="outline" onClick={() => policies.retry()}>다시 불러오기</Button>
      </div>
    );
  } else if (pending.status !== 'ready' || policies.status !== 'ready') {
    body = <p role="status">가입 정보를 불러오는 중…</p>;
  } else {
    const info = pending.data;
    const list = policies.data;
    body = (
      <form onSubmit={(e) => void onSubmit(e, list)} className="login-form" noValidate>
        <p>
          Google 계정 <strong>{info.email}</strong> 로 가입합니다.
        </p>
        <TextField label="이름" name="displayName" autoComplete="name" maxLength={100} defaultValue={info.display_name}
          required />
        <fieldset className="signup-consents">
          <legend>약관 동의</legend>
          {list.map((p) => (
            <label key={p.policy_code} className="login-check">
              <input type="checkbox" name={`consent-${p.policy_code}`} />
              {policyNames[p.policy_code] ?? p.policy_code} 동의 {p.is_required ? '(필수)' : '(선택)'}
              {' '}
              <a href={p.content_url} target="_blank" rel="noreferrer">보기</a>
            </label>
          ))}
        </fieldset>
        {error && <div role="alert" className="login-error">{error}</div>}
        <Button type="submit" disabled={submitting}>{submitting ? '가입 중…' : '동의하고 가입'}</Button>
      </form>
    );
  }

  return (
    <section aria-labelledby="google-signup-title" className="login-page">
      <div className="login-card">
        <h1 id="google-signup-title" className="login-title">Google로 가입</h1>
        {body}
        <p className="login-signup">
          비밀번호 계정이 있나요? <Link to="/login">로그인</Link>
        </p>
      </div>
    </section>
  );
}
