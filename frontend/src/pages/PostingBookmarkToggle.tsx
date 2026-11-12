import { useContext, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { useApi } from '../api/ApiContext';
import { AuthContext } from '../auth/useAuth';
import { Button } from '../components/Button';

/**
 * T40: 공고 상세의 관심 공고 저장·해제 버튼 (PUT/DELETE /me/bookmarks/{id}).
 * - 처음 상태는 공고 상세의 `is_bookmarked`(T18, 로그인했을 때만 true/false)입니다.
 * - 비로그인이면 버튼 대신 로그인 안내를 보여 줍니다. 저장 목록은 /me/bookmarks 화면이 다시 불러옵니다.
 * - 실패하면 상태를 바꾸지 않고 안내만 합니다(서버가 기준).
 */
export function PostingBookmarkToggle({ postingId, initial }: { postingId: string; initial: boolean | null }) {
  const auth = useContext(AuthContext);
  const api = useApi();
  const location = useLocation();
  const [saved, setSaved] = useState(initial === true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  if (auth?.state.status !== 'authenticated') {
    return (
      <p className="t40-bookmark-hint">
        <Link to="/login" state={{ from: location.pathname + location.search }}>로그인</Link>하면 관심 공고로 저장할 수 있어요.
      </p>
    );
  }

  async function toggle() {
    setBusy(true);
    setMessage('');
    try {
      if (saved) await api.me.bookmarks.remove(postingId);
      else await api.me.bookmarks.add(postingId);
      setMessage(saved ? '관심 공고에서 뺐습니다.' : '관심 공고로 저장했습니다.');
      setSaved(!saved);
    } catch {
      setMessage('처리하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="t40-bookmark">
      <Button variant={saved ? 'outline' : 'primary'} aria-pressed={saved} disabled={busy} onClick={() => void toggle()}>
        {saved ? '관심 공고 해제' : '관심 공고 저장'}
      </Button>
      <p role="status" className="t40-bookmark-status">{message}</p>
    </div>
  );
}
