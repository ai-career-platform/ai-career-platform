import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';

/** 로그인 사용자 확인용 계정 화면. 프로필 조회·수정은 T22 에서 구현합니다. */
export function AccountPage() {
  const { state, logout } = useAuth();
  if (state.status !== 'authenticated') return null;
  return (
    <section aria-labelledby="account-title">
      <h1 id="account-title">내 계정</h1>
      <p>
        {state.user.displayName} ({state.user.email})
      </p>
      <p>역할: {state.user.roles.join(', ')}</p>
      <Button variant="outline" onClick={() => void logout()}>
        로그아웃
      </Button>
    </section>
  );
}
