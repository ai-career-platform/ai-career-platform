import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../api/errors';
import { createSkillGapApi } from '../api/skillGaps';
import { useAuth } from '../auth/useAuth';
import { SkillGapPage, type SkillGapPageState } from './SkillGapPage';

type SkillGapResultPageProps = { jobRoleId?: string; assessmentId?: string };

/** Authenticated container; the host route supplies the selected role/result ID. */
export function SkillGapResultPage(props: SkillGapResultPageProps) {
  const { state } = useAuth();
  const [retry, setRetry] = useState(0);
  if (state.status !== 'authenticated') {
    return <SkillGapPage status={{ state: state.status === 'loading' ? 'loading' : 'unauthorized' }} />;
  }
  return <SkillGapResultContent key={`${state.user.email}:${props.jobRoleId ?? ''}:${props.assessmentId ?? ''}:${retry}`} {...props} onRetry={() => setRetry((value) => value + 1)} />;
}

function SkillGapResultContent({ jobRoleId, assessmentId, onRetry }: SkillGapResultPageProps & { onRetry: () => void }) {
  const { request } = useAuth();
  const api = useMemo(() => createSkillGapApi(request), [request]);
  const [status, setStatus] = useState<SkillGapPageState>({ state: 'loading' });
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisFailed, setAnalysisFailed] = useState(false);
  const pending = useRef(false);
  const generation = useRef(0);
  const invalidate = useCallback(() => { generation.current++; }, []);

  useEffect(() => {
    const current = ++generation.current;
    const load = async () => {
      setStatus({ state: 'loading' });
      setAnalysisFailed(false);
      try {
        let id = assessmentId;
        if (!id) {
          const page = await api.list({ job_role_id: jobRoleId, limit: 1 });
          id = page.items[0]?.assessment_id;
        }
        const result = id ? await api.get(id) : null;
        if (generation.current !== current) return;
        setStatus(result ? { state: 'ready', result } : { state: 'empty' });
      } catch (error) {
        if (generation.current !== current) return;
        // A missing specific result is an error, not an empty history.
        setStatus({ state: error instanceof ApiError && error.status === 401 ? 'unauthorized' : 'error' });
      }
    };
    void load();
    return invalidate;
  }, [api, jobRoleId, assessmentId, invalidate]);

  const roleId = jobRoleId ?? (status.state === 'ready' ? status.result.job_role.job_role_id : undefined);
  const analyze = async () => {
    if (!roleId || pending.current) return;
    pending.current = true;
    const current = generation.current;
    setAnalyzing(true);
    setAnalysisFailed(false);
    try {
      const result = await api.create(roleId);
      if (generation.current === current) setStatus({ state: 'ready', result });
    } catch (error) {
      if (generation.current !== current) return;
      if (error instanceof ApiError && error.status === 401) setStatus({ state: 'unauthorized' });
      else setAnalysisFailed(true);
    } finally {
      pending.current = false;
      if (generation.current === current) setAnalyzing(false);
    }
  };

  return <>
    <SkillGapPage status={status} onRetry={onRetry}
      onAnalyze={roleId ? () => { void analyze(); } : undefined}
      analyzing={analyzing} analysisFailed={analysisFailed} />
    {status.state === 'empty' && !roleId && <p>분석할 목표 직무를 선택해 주세요. <a href="/me/target-roles">목표 직무 관리</a></p>}
  </>;
}
