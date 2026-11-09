/**
 * 공고(T24)·직무(T23) 상세에 붙는 "내 적합도 계산" 버튼 (UI-015 진입, T41 POST /v1/matches).
 * 성공하면 결과 화면 /matches/{match_id} 로 이동합니다. 비로그인이면 로그인으로 안내합니다.
 */
import { useId, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useApi } from '../api/ApiContext';
import { matchErrorMessage, type MatchError, type MatchRequest } from '../api/matches';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import './MatchResultPage.css';

/** loginHint=false: 화면에 이미 로그인 안내가 있으면(T23 직무 비교) 중복 안내를 숨깁니다. */
export function MatchAction({ target, targetName, loginHint = true }: { target: MatchRequest; targetName: string; loginHint?: boolean }) {
  const { state } = useAuth();
  const api = useApi();
  const navigate = useNavigate();
  const location = useLocation();
  const hintId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<MatchError | null>(null);

  if (state.status === 'loading') return null;
  if (state.status === 'anonymous') {
    if (!loginHint) return null;
    return (
      <p className="match-action-hint">
        <Link to="/login" state={{ from: location.pathname + location.search }}>로그인</Link>하면 내 보유 기술로 이 {'job_posting_id' in target ? '공고' : '직무'}의 적합도를 계산해 볼 수 있어요.
      </p>
    );
  }

  async function run() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const match = await api.matches.create(target);
      navigate(`/matches/${encodeURIComponent(match.match_id)}`);
    } catch (e) {
      setError(matchErrorMessage(e));
      setBusy(false);
    }
  }

  return (
    <div className="match-action">
      <Button onClick={run} disabled={busy} aria-describedby={hintId}>
        {busy ? '계산 중…' : '내 적합도 계산'}
      </Button>
      <small id={hintId}>{targetName} · 규칙 기반 설명 점수이며 합격 확률이 아닙니다.</small>
      {error && (
        <p role="alert" className="match-action-error">
          {error.message}
          {error.needsSkills && <> <Link to="/me/skills">보유 기술 등록하기</Link></>}
        </p>
      )}
    </div>
  );
}
