import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { FilterChips } from '../components/FilterChips';
import { RecommendationCard } from '../components/RecommendationCard';
import { StatePanel } from '../components/StatePanel';
import {
  createRecommendationRun,
  findLatestRecommendationRun,
  RECOMMENDATION_LIMIT_DEFAULT,
} from '../api/recommendations';
import type { ModelKind, RecommendationItem, RecommendationRun, RecommendationRunStatus } from '../api/recommendations';
import './RecommendationsPage.css';

const statusLabels: Record<RecommendationRunStatus, string> = {
  completed: '맞춤 추천',
  fallback: '기준 추천 (개인화 아님)',
  failed: '추천 실패',
};

const kindLabels: Record<ModelKind, string> = {
  rule: '규칙 기반',
  ml: '머신러닝 모델',
  llm: '언어 모델',
};

type FeedbackFilter = 'all' | 'liked' | 'none' | 'not_interested';
const filterOptions: { value: FeedbackFilter; label: string }[] = [
  { value: 'all', label: '전체' },
  { value: 'liked', label: '좋아요' },
  { value: 'none', label: '피드백 없음' },
  { value: 'not_interested', label: '관심 없음' },
];

const matchesFilter = (item: RecommendationItem, filter: FeedbackFilter) =>
  filter === 'all' || (filter === 'none' ? item.feedback === null : item.feedback === filter);

const generatedAtFormat = new Intl.DateTimeFormat('ko-KR', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Asia/Seoul',
});

type RecommendationsPageProps = {
  /**
   * 카드별 추가 동작(확장 지점). T48 에서 추천 설명 모달·피드백 버튼을 여기에 연결합니다.
   * onRunChange 로 피드백 저장 후 다시 조회한 추천을 화면에 반영합니다.
   */
  renderItemActions?: (item: RecommendationItem, run: RecommendationRun, onRunChange: (run: RecommendationRun) => void) => ReactNode;
};

/** UI-017 맞춤 공고 추천 목록 (FR-ANL-003). 로그인 필요 경로(RequireAuth) 아래에 둡니다. */
export function RecommendationsPage({ renderItemActions }: RecommendationsPageProps = {}) {
  const { request } = useAuth();
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading');
  const [run, setRun] = useState<RecommendationRun | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(false);
  const [filter, setFilter] = useState<FeedbackFilter>('all');

  // 응답이 늦게 온 이전 조회가 최신 상태를 덮어쓰지 않도록 조회마다 번호를 매깁니다.
  const loadSeq = useRef(0);
  const loadLatest = useCallback(() => {
    const seq = ++loadSeq.current;
    findLatestRecommendationRun(request)
      .then((latest) => {
        if (seq !== loadSeq.current) return;
        setRun(latest);
        setPhase('ready');
      })
      .catch(() => {
        if (seq === loadSeq.current) setPhase('error');
      });
  }, [request]);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  const retryLoad = () => {
    setPhase('loading');
    loadLatest();
  };

  const requestNewRun = async () => {
    loadSeq.current += 1; // 진행 중인 조회 결과는 버리고 새 추천을 보여줍니다.
    setCreating(true);
    setCreateError(false);
    try {
      setRun(await createRecommendationRun(request, { limit: RECOMMENDATION_LIMIT_DEFAULT }));
      setFilter('all');
      setPhase('ready');
    } catch {
      setCreateError(true);
    } finally {
      setCreating(false);
    }
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
          onAction={retryLoad}
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
                {run.model_version.model_code} · {run.model_version.version} ({kindLabels[run.model_version.kind]})
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
                        actions={renderItemActions?.(item, run, setRun)}
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
