import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import {
  MAX_PASSWORD, MIN_PASSWORD, recoveryErrorView, type AccountRecoveryService,
} from '../api/accountRecovery';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { TextField } from '../components/TextField';
import { env } from '../config/env';
import { createMockAccountRecoveryService, type MockAccountRecoveryService } from '../mocks/accountRecovery';
import './LoginPage.css';

// Mock 모드 전용 메모리 서비스(합성 계정 user@example.com). 실제 API(T93)는 미병합이라 연결하지 않습니다(HOLD).
const mockService = env.mockEnabled ? createMockAccountRecoveryService() : null;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type View = 'request' | 'sent' | 'reset' | 'done' | 'invalid';

/**
 * UI-N03 계정 복구 (T94). 확정 계약(requestPasswordReset·resetPassword) 기준.
 * - 가입 여부를 드러내지 않습니다(성공 문구 하나).
 * - 메일 링크의 토큰은 화면을 연 즉시 주소에서 지웁니다(기록·Referer·분석 도구로 새지 않게). 콘솔에 남기지 않습니다.
 */
export function PasswordResetPage({ service = mockService }: { service?: AccountRecoveryService | null }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { state } = useAuth();
  const [token, setToken] = useState<string | null>(() => new URLSearchParams(location.search).get('token'));
  const [view, setView] = useState<View>(token ? 'reset' : 'request');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    // 토큰은 메모리(state)에만 두고 주소창·기록에서는 바로 지웁니다.
    if (location.search.includes('token=')) navigate(location.pathname, { replace: true });
  }, [location.pathname, location.search, navigate]);

  // 화면 단계가 바뀌면 제목으로 포커스를 옮겨 스크린리더가 새 단계를 읽게 합니다.
  useEffect(() => { if (view) heading.current?.focus(); }, [view]);

  if (state.status === 'authenticated') {
    return (
      <section className="login-page" aria-labelledby="reset-title">
        <h1 id="reset-title" className="login-title">이미 로그인되어 있습니다</h1>
        <p>비밀번호 재설정은 로그인하지 않은 상태에서 메일 링크로 진행합니다. 계정 정보는 내 계정에서 확인하세요.</p>
        <p><Link to="/account">내 계정으로 이동</Link></p>
      </section>
    );
  }

  if (!service) {
    return (
      <section className="login-page" aria-labelledby="reset-title">
        <h1 id="reset-title" className="login-title">비밀번호 재설정 준비 중</h1>
        <p role="status">비밀번호 재설정 기능은 아직 제공되지 않습니다. 도움이 필요하면 운영자에게 문의해 주세요.</p>
        <p><Link to="/login">로그인으로 돌아가기</Link></p>
      </section>
    );
  }

  async function submitRequest(event: FormEvent) {
    event.preventDefault();
    if (!EMAIL.test(email.trim())) return setError('이메일 주소 형식을 확인해 주세요.');
    setError(null);
    setPending(true);
    try {
      await service!.requestReset({ email: email.trim() });
      setView('sent');
    } catch (failure) {
      setError(recoveryErrorView(failure).message);
    } finally {
      setPending(false);
    }
  }

  async function submitReset(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD || password.length > MAX_PASSWORD) {
      return setError(`새 비밀번호는 ${MIN_PASSWORD}자 이상 ${MAX_PASSWORD}자 이하로 입력해 주세요.`);
    }
    if (password !== confirm) return setError('두 비밀번호가 같지 않습니다.');
    setError(null);
    setPending(true);
    try {
      await service!.resetPassword({ token: token ?? '', new_password: password });
      setToken(null);
      setPassword('');
      setConfirm('');
      setView('done');
    } catch (failure) {
      const problem = recoveryErrorView(failure);
      if (problem.kind === 'invalid-token') {
        setToken(null);
        setView('invalid');
      } else {
        setError(problem.message);
      }
    } finally {
      setPending(false);
    }
  }

  function startOver() {
    setError(null);
    setView('request');
  }

  const title = { request: '비밀번호 재설정', sent: '메일을 확인해 주세요', reset: '새 비밀번호 설정',
    done: '비밀번호를 바꿨습니다', invalid: '링크를 사용할 수 없습니다' }[view];
  const mockLink = view === 'sent' && service === mockService ? (mockService as MockAccountRecoveryService).lastIssuedToken() : null;

  return (
    <section className="login-page" aria-labelledby="reset-title">
      <h1 id="reset-title" className="login-title" ref={heading} tabIndex={-1}>{title}</h1>
      {error && <p role="alert" className="login-error">{error}</p>}

      {view === 'request' && (
        <form className="login-form" onSubmit={submitRequest} noValidate aria-label="비밀번호 재설정 메일 요청">
          <p>가입할 때 쓴 이메일 주소를 입력하면 재설정 링크를 보내 드립니다.</p>
          <TextField label="이메일" type="email" autoComplete="email" required value={email}
            onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" disabled={pending}>{pending ? '요청 중…' : '재설정 링크 받기'}</Button>
          <p><Link to="/login">로그인으로 돌아가기</Link></p>
        </form>
      )}

      {view === 'sent' && (
        <div role="status">
          <p>입력한 주소로 가입된 계정이 있으면 30분 동안 쓸 수 있는 재설정 링크를 보냈습니다.</p>
          <p>메일이 오지 않으면 스팸함을 확인하거나 잠시 후 다시 요청해 주세요.</p>
          <Button variant="outline" onClick={startOver}>다시 요청</Button>
          {mockLink && (
            <p className="login-signup">가상 메일함(Mock 모드 전용): <Link to={`/password-reset?token=${encodeURIComponent(mockLink)}`}>재설정 링크 열기</Link></p>
          )}
        </div>
      )}

      {view === 'reset' && (
        <form className="login-form" onSubmit={submitReset} noValidate aria-label="새 비밀번호 설정">
          <TextField label="새 비밀번호" type="password" autoComplete="new-password" required value={password}
            hint={`${MIN_PASSWORD}자 이상`} onChange={(e) => setPassword(e.target.value)} />
          <TextField label="새 비밀번호 확인" type="password" autoComplete="new-password" required value={confirm}
            onChange={(e) => setConfirm(e.target.value)} />
          <p>바꾸면 모든 기기에서 로그아웃됩니다.</p>
          <Button type="submit" disabled={pending}>{pending ? '변경 중…' : '비밀번호 바꾸기'}</Button>
        </form>
      )}

      {view === 'done' && (
        <div role="status">
          <p>모든 기기에서 로그아웃되었습니다. 새 비밀번호로 다시 로그인해 주세요.</p>
          <p><Link to="/login">로그인하기</Link></p>
        </div>
      )}

      {view === 'invalid' && (
        <div>
          <p>재설정 링크가 만료되었거나(30분), 이미 사용되었거나, 올바르지 않습니다.</p>
          <Button onClick={startOver}>새 링크 요청</Button>
        </div>
      )}
    </section>
  );
}
