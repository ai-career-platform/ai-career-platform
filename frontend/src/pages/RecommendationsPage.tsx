import { useState } from 'react';
import type { ReactNode } from 'react';
import { useApi } from '../api/ApiContext';
import { useQuery } from '../api/useQuery';
import { Button } from '../components/Button';
import { FilterChips } from '../components/FilterChips';
import { RecommendationCard } from '../components/RecommendationCard';
import { StatePanel } from '../components/StatePanel';
import { RECOMMENDATION_LIMIT_DEFAULT } from '../api/recommendations';
import type { RecommendationItem, RecommendationRun } from '../api/recommendations';
import {
  feedbackButtonLabels,
  formatModelVersion,
  generatedAtFormat,
  recommendationStatusLabels as statusLabels,
} from '../components/recommendationLabels';
import './RecommendationsPage.css';

type FeedbackFilter = 'all' | 'liked' | 'none' | 'not_interested';
const filterOptions: { value: FeedbackFilter; label: string }[] = [
  { value: 'all', label: '전체' },
  { value: 'liked', label: feedbackButtonLabels.liked },
  { value: 'none', label: '피드백 없음' },
  { value: 'not_interested', label: feedbackButtonLabels.not_interested },
];

const matchesFilter = (item: RecommendationItem, filter: FeedbackFilter) =>
  filter === 'all' || (filter === 'none' ? item.feedback === null : item.feedback === filter);

type RecommendationsPageProps = {
  /**
   * 카드별 추가 동작(확장 지점). T48 에서 추천 설명 모달·피드백 버튼을 여기에 연결합니다.
   * onRunChange 로 피드백 저장 후 다시 조회한 추천을 화면에 반영합니다.
   */
  renderItemActions?: (item: RecommendationItem, run: RecommendationRun, onRunChange: (run: RecommendationRun) => void) => ReactNode;
};

/** UI-017 맞춤 공고 추천 목록 (FR-ANL-003). 로그인 필요 경로(RequireAuth) 아래에 둡니다. */
export function RecommendationsPage({ renderItemActions }: RecommendationsPageProps = {}) {
  const api = useApi();
  // 가장 최근 추천(없으면 null). 늦게 온 이전 조회가 최신 상태를 덮어쓰지 않는 것은 useQuery 가 맡습니다.
  const latest = useQuery(['recommendation-latest'], (signal) => api.recommendations.findLatest(signal));
  // 새로 받은 추천·피드백 반영 후 다시 조회한 추천. 있으면 조회 결과보다 우선합니다.
  const [override, setOverride] = useState<RecommendationRun | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(false);
  const [filter, setFilter] = useState<FeedbackFilter>('all');

  const phase: 'loading' | 'ready' | 'error' = override ? 'ready' : latest.status === 'ready' ? 'ready' : latest.status === 'error' ? 'error' : 'loading';
  const run = override ?? (latest.status === 'ready' ? latest.data : null);
  const setRun = (next: RecommendationRun) => setOverride(next);

  const requestNewRun = async () => {
    setCreating(true);
    setCreateError(false);
    try {
      // 진행 중인 조회가 나중에 끝나도 새 추천이 우선합니다(override).
      setRun(await api.recommendations.create({ limit: RECOMMENDATION_LIMIT_DEFAULT }));
      setFilter('all');
    } catch {
      setCreateError(true);
    } finally {
      setCreating(false);
    }
  };

  // 피드백 저장 후 다시 조회한 추천을 반영합니다. 그 사이 새 추천을 받았다면 이전 실행 결과로 덮어쓰지 않습니다.
  const latestRun = latest.status === 'ready' ? latest.data : null;
  const applyRunChange = (next: RecommendationRun) => {
    setOverride((current) => {
      const shown = current ?? latestRun;
      return shown && shown.recommendation_run_id === next.recommendation_run_id ? next : current;
    });
  };

  const visibleItems = run ? run.items.filter((item) => matchesFilter(item, filter)) : [];

  return (
    <section className="recommendations-page" aria-labelledby="recommendations-title">
      <div className="recommendations-heading">
        <div>
          <h1 id="recommendations-title">맞춤 공고 추천</h1>
          <p className="recommendations-intro">
            목표 직무와 보유 기술을 기준으로 계산한 참고용 추천입니다. AI의 확정 판단이 아니므로 공고 내용을 직접 확인해 주세요.
          </p>
        </div>
        {phase === 'ready' && run && (
          <Button variant="outline" onClick={() => void requestNewRun()} disabled={creating}>
            {creating ? '추천 계산 중…' : '새 추천 받기'}
          </Button>
        )}
      </div>

      {createError && (
        <p className="recommendations-error" role="alert">
          새 추천을 받지 못했습니다. 잠시 후 다시 시도해 주세요.
        </p>
      )}

      {phase === 'loading' && <StatePanel variant="loading" title="추천을 불러오는 중입니다" />}

      {phase === 'error' && (
        <StatePanel
          variant="error"
          title="추천을 불러오지 못했습니다"
          description="잠시 후 다시 시도해 주세요."
          actionLabel="다시 시도"
          onAction={latest.retry}
        />
      )}

      {phase === 'ready' && !run &&
        (creating ? (
          <StatePanel variant="loading" title="추천을 계산하는 중입니다" />
        ) : (
          <StatePanel
            variant="empty"
            title="아직 받은 추천이 없습니다"
            description="목표 직무와 보유 기술을 기준으로 맞춤 공고 추천을 받아 보세요. 기술·목표 직무 정보가 부족하면 기준 추천이 표시될 수 있습니다."
            actionLabel="추천 받기"
            onAction={() => void requestNewRun()}
          />
        ))}

      {phase === 'ready' && run && (
        <>
          <dl className="recommendations-basis" aria-label="추천 기준">
            <div>
              <dt>추천 상태</dt>
              <dd>
                <span className={`recommendations-badge recommendations-badge--${run.status}`}>
                  {statusLabels[run.status]}
                </span>
              </dd>
            </div>
            <div>
              <dt>계산 기준</dt>
              <dd>
                {formatModelVersion(run.model_version)}
              </dd>
            </div>
            <div>
              <dt>생성 시각</dt>
              <dd>
                <time dateTime={run.generated_at}>{generatedAtFormat.format(new Date(run.generated_at))}</time>
              </dd>
            </div>
          </dl>

          {run.status === 'fallback' && (
            <p className="recommendations-notice" role="note">
              맞춤 추천을 계산하지 못해 개인화되지 않은 최근 공고(기준 추천)를 대신 보여 드립니다. 보유 기술·목표 직무 정보가
              부족하면 이렇게 표시될 수 있습니다.
            </p>
          )}

          {run.status === 'failed' ? (
            <StatePanel
              variant="error"
              title="추천 계산에 실패했습니다"
              description="잠시 후 새 추천을 다시 받아 주세요."
              actionLabel="다시 추천 받기"
              onAction={() => void requestNewRun()}
            />
          ) : run.items.length === 0 ? (
            <StatePanel
              variant="empty"
              title="추천할 공고가 없습니다"
              description="게시 중인 공고가 없거나, 관심 없음으로 표시한 공고가 제외되었습니다."
            />
          ) : (
            <>
              <FilterChips
                label="피드백 상태로 거르기"
                options={filterOptions}
                value={filter}
                onChange={(value) => setFilter(value as FeedbackFilter)}
              />
              <p className="recommendations-count" aria-live="polite">
                {run.items.length}개 중 {visibleItems.length}개 표시
              </p>
              {visibleItems.length === 0 ? (
                <StatePanel
                  variant="empty"
                  title="조건에 맞는 추천이 없습니다"
                  description="다른 피드백 상태를 선택해 주세요."
                  actionLabel="필터 초기화"
                  onAction={() => setFilter('all')}
                />
              ) : (
                <ol className="recommendations-list" aria-label="추천 공고 목록">
                  {visibleItems.map((item) => (
                    <li key={item.job_posting.job_posting_id}>
                      <RecommendationCard
                        item={item}
                        personalized={run.status === 'completed'}
                        actions={renderItemActions?.(item, run, applyRunChange)}
                      />
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
