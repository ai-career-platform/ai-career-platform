import { Link } from 'react-router';
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
    </section>
  );
}
