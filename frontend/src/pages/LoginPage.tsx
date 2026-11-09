import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { ApiError } from '../api/client';
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
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (state.status === 'authenticated') return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    setSubmitting(true);
    try {
      await login(String(form.get('email')).trim(), String(form.get('password')));
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
        <h1 id="login-title">로그인</h1>
        <form onSubmit={onSubmit} className="login-form">
          <TextField label="이메일" name="email" type="email" autoComplete="username" required />
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
        </form>
      </div>
    </section>
  );
}
