import { useRef, useState } from 'react';
import { useApi } from '../api/ApiContext';
import { ApiError } from '../api/errors';
import type { SkillGap } from '../api/skillGaps';
import { useQuery } from '../api/useQuery';
import { useAuth } from '../auth/useAuth';
import { SkillGapPage, type SkillGapPageState } from './SkillGapPage';

type SkillGapResultPageProps = { jobRoleId?: string; assessmentId?: string };

const isUnauthorized = (error: unknown) => error instanceof ApiError && error.status === 401;

/** Authenticated container; the host route supplies the selected role/result ID. */
export function SkillGapResultPage(props: SkillGapResultPageProps) {
  const { state } = useAuth();
  const [retry, setRetry] = useState(0);
  if (state.status !== 'authenticated') {
    return <SkillGapPage status={{ state: state.status === 'loading' ? 'loading' : 'unauthorized' }} />;
  }
  // 사용자·직무·결과가 바뀌거나 다시 시도하면 새로 마운트해 이전 분석 상태를 남기지 않습니다.
  return <SkillGapResultContent key={`${state.user.email}:${props.jobRoleId ?? ''}:${props.assessmentId ?? ''}:${retry}`} {...props} onRetry={() => setRetry((value) => value + 1)} />;
}

function SkillGapResultContent({ jobRoleId, assessmentId, onRetry }: SkillGapResultPageProps & { onRetry: () => void }) {
  const api = useApi();
  // 지정 결과가 없으면 이력의 최신 1건을 찾아 상세를 불러옵니다. 이력이 비면 null.
  const latest = useQuery(['skill-gap', jobRoleId ?? null, assessmentId ?? null], async (signal) => {
    let id = assessmentId;
    if (!id) {
      const page = await api.skillGaps.list({ job_role_id: jobRoleId, limit: 1 }, signal);
      id = page.items[0]?.assessment_id;
    }
    return id ? await api.skillGaps.get(id, signal) : null;
  });
  const [analyzed, setAnalyzed] = useState<SkillGap | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisFailed, setAnalysisFailed] = useState(false);
  const [unauthorized, setUnauthorized] = useState(false);
  const pending = useRef(false);

  const status: SkillGapPageState = unauthorized ? { state: 'unauthorized' }
    : analyzed ? { state: 'ready', result: analyzed }
      : latest.status === 'ready' ? (latest.data ? { state: 'ready', result: latest.data } : { state: 'empty' })
        // A missing specific result is an error, not an empty history.
        : latest.status === 'error' ? { state: isUnauthorized(latest.error) ? 'unauthorized' : 'error' }
          : { state: 'loading' };

  const roleId = jobRoleId ?? (status.state === 'ready' ? status.result.job_role.job_role_id : undefined);
  const analyze = async () => {
    if (!roleId || pending.current) return;
    pending.current = true;
    setAnalyzing(true);
    setAnalysisFailed(false);
    try {
      setAnalyzed(await api.skillGaps.create(roleId));
    } catch (error) {
      if (isUnauthorized(error)) setUnauthorized(true);
      else setAnalysisFailed(true);
    } finally {
      pending.current = false;
      setAnalyzing(false);
    }
  };

  return <>
    <SkillGapPage status={status} onRetry={onRetry}
      onAnalyze={roleId ? () => { void analyze(); } : undefined}
      analyzing={analyzing} analysisFailed={analysisFailed} />
    {status.state === 'empty' && !roleId && <p>분석할 목표 직무를 선택해 주세요. <a href="/me/target-roles">목표 직무 관리</a></p>}
  </>;
}
