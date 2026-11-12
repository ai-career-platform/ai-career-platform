import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router';
import { ApiError } from '../api/client';
import { useApi } from '../api/ApiContext';
import { policyNames } from '../api/privacy';
import type { ConsentPolicy } from '../api/privacy';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { TextField } from '../components/TextField';
import './LoginPage.css';

const MIN_PASSWORD = 10;

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return '이미 가입된 이메일입니다. 로그인하거나 비밀번호 찾기를 이용해 주세요.';
    if (error.status === 422) return error.userMessage ?? '입력값을 확인해 주세요.';
    if (error.status === 429) return '시도 횟수가 많습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 0) return '서버에 연결할 수 없습니다. 네트워크를 확인해 주세요.';
  }
  return '회원가입 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.';
}

/** 회원가입 화면 (UI-001 가입, FR-ACC-001). 가입에 성공하면 바로 로그인 상태로 내 계정 화면에 갑니다. */
export function SignupPage() {
  const { state, signup } = useAuth();
  const api = useApi();
  const navigate = useNavigate();
  const policies = useQuery(['consent-policies'], (signal) => api.me.consents.policies(signal));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (state.status === 'authenticated') return <Navigate to="/account" replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>, list: ConsentPolicy[]) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get('password'));
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError(`비밀번호는 ${MIN_PASSWORD}자 이상이어야 합니다.`);
      return;
    }
    if (password !== String(form.get('passwordConfirm'))) {
      setError('비밀번호 확인이 일치하지 않습니다.');
      return;
    }
    setSubmitting(true);
    try {
      await signup({
        email: String(form.get('email')).trim(),
        password,
        display_name: String(form.get('displayName')).trim(),
        consents: list.map((p) => ({
          policy_code: p.policy_code,
          policy_version: p.version,
          granted: form.get(`consent-${p.policy_code}`) === 'on',
        })),
      });
      navigate('/account', { replace: true });
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="signup-title" className="login-page">
      <div className="login-card">
        <h1 id="signup-title" className="login-title">
          회원가입
        </h1>
        {(policies.status === 'loading' || policies.status === 'idle') && <p role="status">약관 정보를 불러오는 중…</p>}
        {policies.status === 'error' && (
          <p role="alert" className="login-error">
            약관 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </p>
        )}
        {policies.status === 'ready' && (
          <form onSubmit={(e) => onSubmit(e, policies.data)} className="login-form">
            <TextField label="이메일" name="email" type="email" autoComplete="email" required />
            <TextField label="이름" name="displayName" autoComplete="name" maxLength={50} required />
            <TextField
              label="비밀번호"
              name="password"
              type="password"
              autoComplete="new-password"
              hint={`${MIN_PASSWORD}자 이상`}
              minLength={MIN_PASSWORD}
              required
            />
            <TextField
              label="비밀번호 확인"
              name="passwordConfirm"
              type="password"
              autoComplete="new-password"
              required
            />
            <fieldset className="signup-consents">
              <legend>약관 동의</legend>
              {policies.data.map((p) => (
                <label key={p.policy_code} className="login-check">
                  <input type="checkbox" name={`consent-${p.policy_code}`} required={p.is_required} />
                  {policyNames[p.policy_code] ?? p.policy_code} 동의 {p.is_required ? '(필수)' : '(선택)'}
                  {' '}
                  <a href={p.content_url} target="_blank" rel="noreferrer">
                    보기
                  </a>
                </label>
              ))}
            </fieldset>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <Button type="submit" disabled={submitting}>
              {submitting ? '가입 중…' : '회원가입'}
            </Button>
          </form>
        )}
        <p className="login-signup">
          이미 회원이신가요? <Link to="/login">로그인</Link>
        </p>
      </div>
    </section>
  );
}
