import { Link } from 'react-router';
import { useGoogleAvailable } from '../auth/useGoogleAvailable';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';

/** 로그인 사용자 확인용 계정 화면. 프로필 조회·수정은 T22 에서 구현합니다. */
export function AccountPage() {
  const { state, logout, fullLogout } = useAuth();
  const googleAvailable = useGoogleAvailable();
  if (state.status !== 'authenticated') return null;
  return (
    <section aria-labelledby="account-title">
      <h1 id="account-title">내 계정</h1>
      <p>
        {state.user.displayName} ({state.user.email})
      </p>
      <p><Link to="/account/privacy">개인정보 설정·동의 관리</Link></p>
      <p><Link to="/me/skills">나의 기술 관리</Link></p>
      <p><Link to="/me/documents">내 문서 관리</Link></p>
      {/* T92: 아래 세 화면은 경로만 있고 앱 안에서 들어갈 링크가 없었습니다(추천은 목표 직무가 필요). */}
      <p><Link to="/me/target-roles">목표 직무 설정</Link></p>
      <p><Link to="/me/career-history">경력·프로젝트 관리</Link></p>
      <p><Link to="/me/bookmarks">저장한 공고</Link></p>
      <p>역할: {state.user.roles.join(', ')}</p>
      <Button variant="outline" onClick={() => void logout()}>
        로그아웃
      </Button>
      {googleAvailable && (
        <>
          {' '}
          <Button variant="outline" onClick={() => void fullLogout()} aria-describedby="full-logout-help">
            완전 로그아웃
          </Button>
          <p id="full-logout-help">
            완전 로그아웃은 이 브라우저에서 AI Career 로그인과 Google 접근 확인을 모두 지웁니다. Google 계정 자체는
            로그아웃되지 않습니다.
          </p>
        </>
      )}
    </section>
  );
}
