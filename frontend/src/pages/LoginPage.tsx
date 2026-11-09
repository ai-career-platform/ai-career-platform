import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
import { ApiError } from '../api/client';
import { getSavedEmail, saveEmail } from '../auth/loginPreferences';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { TextField } from '../components/TextField';
import './LoginPage.css';

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return '이메일 또는 비밀번호가 올바르지 않습니다.';
    if (error.status === 429) return '시도 횟수가 많습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 0) return '서버에 연결할 수 없습니다. 네트워크를 확인해 주세요.';
  }
  return '로그인 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.';
}

/** 로그인 화면 (UI-001). 이미 로그인했다면 돌아갈 경로로 이동합니다. */
export function LoginPage() {
  const { state, login } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/account';
  const [savedEmail] = useState(getSavedEmail);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (state.status === 'authenticated') return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get('email')).trim();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, String(form.get('password')), form.get('autoLogin') === 'on');
      saveEmail(form.get('saveEmail') === 'on' ? email : null); // 로그인에 성공했을 때만 갱신
      navigate(from, { replace: true });
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="login-title" className="login-page">
      <div className="login-card">
        <div className="login-avatar" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c1-4 4-6 8-6s7 2 8 6" />
          </svg>
        </div>
        <h1 id="login-title" className="login-title">
          로그인
        </h1>
        <form onSubmit={onSubmit} className="login-form">
          <TextField
            label="이메일"
            name="email"
            type="email"
            autoComplete="username"
            defaultValue={savedEmail}
            required
          />
          <TextField
            label="비밀번호"
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
          {error && (
            <p role="alert" className="login-error">
              {error}
            </p>
          )}
          <Button type="submit" disabled={submitting}>
            {submitting ? '로그인 중…' : '로그인'}
          </Button>
          {/* 비밀번호 찾기·회원가입 화면은 아직 없어(T94 등) 누르면 "페이지를 찾을 수 없음"이 보입니다. */}
          <div className="login-options">
            <label className="login-check">
              <input type="checkbox" name="saveEmail" defaultChecked={savedEmail !== ''} />
              아이디 저장
            </label>
            <label className="login-check">
              <input type="checkbox" name="autoLogin" />
              자동 로그인
            </label>
            <Link to="/password-reset" className="login-forgot">
              비밀번호를 잊으셨나요?
            </Link>
          </div>
        </form>
        <p className="login-signup">
          아직 회원이 아니신가요? <Link to="/signup">회원가입</Link>
        </p>
      </div>
    </section>
  );
}
