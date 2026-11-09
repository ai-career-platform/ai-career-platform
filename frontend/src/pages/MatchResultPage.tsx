/**
 * UI-015 적합도 결과 (T42, F-015). API: T41 GET/POST /v1/matches, T18 공고 상세, T17 직무 상세, T33 내 보유 기술.
 *
 * - 점수·충족/부족 수·한계 설명·계산 기준·분석 시점은 서버 결과(Match)를 그대로 보여 준다. 화면에서 점수를 다시 만들지 않는다.
 * - 점수는 규칙 기반 설명 점수(0~100)다. 합격 확률·백분위·순위로 표현하지 않는다(% 기호도 쓰지 않음).
 * - 근거 표는 대상의 요구 기술과 "지금" 내 보유 기술을 견준 것이다. T41이 계산 입력값을 저장하지 않아
 *   계산 뒤 보유 기술을 바꾸면 점수와 다를 수 있으므로 그 사실을 화면에 밝힌다.
 */
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useApi } from '../api/ApiContext';
import { ApiError } from '../api/errors';
import { formatEvaluatedAt, formatScore, matchErrorMessage } from '../api/matches';
import type { MatchError, MatchRequest } from '../api/matches';
import { useQuery } from '../api/useQuery';
import { Button } from '../components/Button';
import { StatePanel } from '../components/StatePanel';
import { EVIDENCE_LABEL, buildEvidence, shortLevel } from './matchEvidence';
import type { EvidenceRequirement } from './matchEvidence';
import { uuidOrEmpty } from './postingFormat';
import './MatchResultPage.css';

type TargetDetail = { name: string; subtitle: string; requirements: EvidenceRequirement[] };

const SCORE_NOTE = '보유 기술·숙련도를 요구 기술과 비교한 규칙 기반 설명 점수(0~100)입니다. 합격 확률이나 다른 지원자와의 비교 순위가 아닙니다.';
const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

export function MatchResultPage() {
  const api = useApi();
  const navigate = useNavigate();
  const matchId = uuidOrEmpty(useParams().matchId ?? null);
  const [rerun, setRerun] = useState<{ busy: boolean; error: MatchError | null }>({ busy: false, error: null });

  const loaded = useQuery(matchId !== '' && ['match', matchId], (signal) => api.matches.get(matchId, signal));
  const match = loaded.status === 'ready' ? loaded.data : null;

  const postingId = match?.target.job_posting_id ?? null;
  const roleId = match?.target.job_role_id ?? null;
  // 대상 정보는 공개 카탈로그 API(T18 공고 / T17 직무)에서 이름·요구 기술만 가져옵니다.
  const target = useQuery<TargetDetail>(match !== null && ['match-target', postingId, roleId], async (signal) => {
    if (postingId) {
      const d = await api.jobPostings.get(postingId, signal);
      return { name: d.title, subtitle: `${d.company.name} · ${d.job_role?.name ?? '직무 미등록'}`, requirements: d.required_skills };
    }
    const d = await api.jobRoles.get(roleId ?? '', signal);
    return { name: d.name, subtitle: `직무 · ${d.code}`, requirements: d.required_skills.map(({ skill, required_level }) => ({ skill, required_level })) };
  });
  // 근거 표는 "지금" 내 보유 기술(T33). 결과가 바뀌면(다시 계산) 같이 다시 불러옵니다.
  const mySkills = useQuery(match !== null && ['me-skills', matchId], (signal) => api.me.skills.list(signal));

  async function recalculate() {
    if (!match || rerun.busy) return;
    const next: MatchRequest = postingId ? { job_posting_id: postingId } : { job_role_id: roleId ?? '' };
    setRerun({ busy: true, error: null });
    try {
      const created = await api.matches.create(next);
      setRerun({ busy: false, error: null });
      navigate(`/matches/${encodeURIComponent(created.match_id)}`);
    } catch (error) {
      setRerun({ busy: false, error: matchErrorMessage(error) });
    }
  }

  if (!matchId || (loaded.status === 'error' && isNotFound(loaded.error))) {
    return (
      <div className="match-page">
        <StatePanel variant="empty" title="적합도 결과를 찾을 수 없습니다"
          description="주소가 잘못되었거나 내 계정의 결과가 아닙니다. 공고나 직무 화면에서 다시 계산해 주세요." />
        <p className="match-links"><Link to="/job-postings">채용공고 보기</Link> · <Link to="/job-roles">직무 탐색</Link></p>
      </div>
    );
  }
  if (loaded.status !== 'ready' || !match) {
    return (
      <div className="match-page">
        {loaded.status === 'error'
          ? <StatePanel variant="error" title="적합도 결과를 불러오지 못했습니다" actionLabel="다시 시도" onAction={loaded.retry} />
          : <StatePanel variant="loading" title="적합도 결과를 불러오는 중입니다" />}
      </div>
    );
  }

  const evidence = target.status === 'ready' && mySkills.status === 'ready'
    ? buildEvidence(target.data.requirements, mySkills.data) : null;
  const kindLabel = postingId ? '공고' : '직무';

  return (
    <div className="match-page">
      <header className="match-header">
        <p className="match-eyebrow">MATCH RESULT · {kindLabel}</p>
        {target.status === 'ready' && <h1>{target.data.name}</h1>}
        {target.status === 'ready' && <p>{target.data.subtitle}</p>}
        {target.status === 'loading' && <h1>{kindLabel} 적합도 결과</h1>}
        {target.status === 'error' && (
          <>
            <h1>{kindLabel} 적합도 결과</h1>
            <p role="alert">{kindLabel} 정보를 불러오지 못했습니다. <button type="button" className="match-link" onClick={target.retry}>다시 시도</button></p>
          </>
        )}
      </header>

      <section className="match-card" aria-labelledby="match-score-title">
        <h2 id="match-score-title" className="visually-hidden">적합도 점수</h2>
        {match.status === 'completed' && match.score !== null && (
          <>
            <p className="match-score" aria-label={`적합도 ${formatScore(match.score)}점 (100점 만점)`}>
              <strong>{formatScore(match.score)}</strong><span>/ 100</span>
            </p>
            <dl className="match-counts">
              <div><dt>충족한 요구 기술</dt><dd>{match.matched_skill_count ?? '—'}개</dd></div>
              <div><dt>부족한 요구 기술</dt><dd>{match.missing_skill_count ?? '—'}개</dd></div>
            </dl>
          </>
        )}
        {match.status === 'failed' && (
          <div className="match-failed">
            <strong>점수를 계산하지 못했습니다</strong>
            <p>아래 한계 설명을 확인해 주세요.</p>
          </div>
        )}
        {match.status === 'pending' && (
          <div className="match-failed">
            <strong>아직 계산 중입니다</strong>
            <Button variant="outline" onClick={loaded.retry}>결과 새로고침</Button>
          </div>
        )}
        <p className="match-note">{SCORE_NOTE}</p>
      </section>

      <section className="match-section" aria-labelledby="match-limits-title">
        <h2 id="match-limits-title">한계 설명</h2>
        <ul className="match-limits">
          {match.limitations.map((text) => <li key={text}>{text}</li>)}
        </ul>
      </section>

      <section className="match-section" aria-labelledby="match-basis-title">
        <h2 id="match-basis-title">계산 기준</h2>
        <dl className="match-basis">
          <div><dt>계산 규칙</dt><dd>{match.model_version.model_code} v{match.model_version.version} ({match.model_version.kind === 'rule' ? '규칙 기반' : match.model_version.kind})</dd></div>
          <div><dt>분석 시점</dt><dd><time dateTime={match.evaluated_at}>{formatEvaluatedAt(match.evaluated_at)}</time></dd></div>
        </dl>
      </section>

      <section className="match-section" aria-labelledby="match-evidence-title">
        <h2 id="match-evidence-title">근거 · 부족 역량</h2>
        <p className="match-note">
          요구 기술과 <strong>지금</strong> 내 보유 기술을 견준 표입니다. 계산 뒤에 보유 기술을 바꿨다면 위 점수와 다를 수 있어요.
          프로젝트에서만 사용한 기술은 점수에는 반영되지만 이 표에는 나오지 않습니다.
        </p>
        {(target.status === 'loading' || mySkills.status === 'loading') && <p role="status">근거를 불러오는 중입니다.</p>}
        {mySkills.status === 'error' && (
          <StatePanel variant="error" title="내 보유 기술을 불러오지 못했습니다" actionLabel="다시 시도" onAction={mySkills.retry} />
        )}
        {evidence && evidence.length === 0 && <p>이 {kindLabel}에는 등록된 요구 기술이 없습니다.</p>}
        {evidence && evidence.length > 0 && (
          <table className="match-evidence">
            <caption className="visually-hidden">요구 기술별 내 수준 비교</caption>
            <thead><tr><th scope="col">기술</th><th scope="col">구분</th><th scope="col">요구 수준</th><th scope="col">내 수준</th><th scope="col">상태</th></tr></thead>
            <tbody>
              {evidence.map((row) => (
                <tr key={row.skillId}>
                  <th scope="row">{row.name}</th>
                  <td data-label="구분">{row.required ? '필수' : '우대'}</td>
                  <td data-label="요구">{row.requiredLevel === null ? '미등록' : shortLevel(row.requiredLevel)}</td>
                  <td data-label="내 수준">{shortLevel(row.myLevel)}</td>
                  <td><span className={`match-badge match-badge--${row.status}`}>{EVIDENCE_LABEL[row.status]}{row.gap ? ` (${row.gap}단계)` : ''}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="match-actions">
        <Button onClick={recalculate} disabled={rerun.busy}>{rerun.busy ? '계산 중…' : '지금 보유 기술로 다시 계산'}</Button>
        <Link to="/me/skills">보유 기술 수정</Link>
        <Link to={postingId ? '/job-postings' : '/job-roles'}>{kindLabel} 목록으로</Link>
      </div>
      {rerun.error && (
        <p role="alert" className="match-action-error">
          {rerun.error.message}
          {rerun.error.needsSkills && <> <Link to="/me/skills">보유 기술 등록하기</Link></>}
        </p>
      )}
    </div>
  );
}
