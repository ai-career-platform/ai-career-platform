import { useContext, useState } from 'react';
import { Link } from 'react-router';
import { useApi } from '../api/ApiContext';
import { ApiError } from '../api/errors';
import { AuthContext } from '../auth/useAuth';
import { Button } from '../components/Button';
import { env } from '../config/env';

/**
 * T103: 공고 상세에서 "지원 기록에 추가" (POST /me/job-applications, T102).
 * - VITE_APPLICATIONS_UI 가 켜지고 Mock 모드가 아닐 때만 보입니다(Mock 보드는 자체 가상 데이터를 씁니다).
 * - 로그인한 사용자만. 비로그인 안내는 바로 위 관심 공고 버튼이 이미 보여 줍니다.
 * - 같은 공고를 이미 기록했으면(409) 지원 현황으로 가는 링크만 안내합니다. 실패 시 상태를 바꾸지 않습니다.
 */
export function PostingApplicationButton({ postingId, enabled = env.applicationsUi && !env.mockEnabled }:
  { postingId: string; enabled?: boolean }) {
  const auth = useContext(AuthContext);
  const api = useApi();
  const [state, setState] = useState<'idle' | 'busy' | 'added' | 'exists' | 'error'>('idle');

  if (!enabled || auth?.state.status !== 'authenticated') return null;

  async function add() {
    setState('busy');
    try {
      await api.jobApplications.create({ job_posting_id: postingId });
      setState('added');
    } catch (error) {
      setState(error instanceof ApiError && error.status === 409 ? 'exists' : 'error');
    }
  }

  const done = state === 'added' || state === 'exists';
  return (
    <div className="t103-add-application">
      <Button variant="outline" disabled={state === 'busy' || done} onClick={() => void add()}>
        {done ? '지원 기록에 있음' : '지원 기록에 추가'}
      </Button>
      <p role="status" className="t103-add-application-status">
        {state === 'added' && <>지원 기록에 추가했습니다. <Link to="/me/applications">지원 현황 보기</Link></>}
        {state === 'exists' && <>이미 지원 기록에 있는 공고입니다. <Link to="/me/applications">지원 현황 보기</Link></>}
        {state === 'error' && '추가하지 못했습니다. 잠시 후 다시 시도해 주세요.'}
      </p>
    </div>
  );
}
