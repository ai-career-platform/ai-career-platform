import { useRef, useState } from 'react';
import { useApi } from '../api/ApiContext';
import { ApiError } from '../api/errors';
import { applyFeedbackToRun } from '../api/recommendations';
import type {
  RecommendationFeedbackChoice,
  RecommendationFeedbackValue,
  RecommendationItem,
  RecommendationRun,
} from '../api/recommendations';
import './Button.css';
import { RecommendationExplanationDialog } from './RecommendationExplanationDialog';
import { FEEDBACK_USAGE_NOTE, feedbackButtonLabels } from './recommendationLabels';
import './RecommendationFeedbackActions.css';

const choices: readonly RecommendationFeedbackValue[] = ['liked', 'not_interested'];

const savedMessages: Record<RecommendationFeedbackChoice, string> = {
  liked: '관심 있음으로 저장했어요.',
  not_interested: '관심 없음으로 저장했어요. 다음 추천부터 이 공고는 제외돼요.',
  cleared: '피드백을 취소했어요.',
};

/** 저장 실패 상태. retryable=false 는 같은 본문을 다시 보내도 실패하는 경우(404·422)입니다. */
type FeedbackFailure = { choice: RecommendationFeedbackChoice; retryable: boolean };

/** 404 NOT_FOUND(내 추천에 없는 공고·실행)·422 VALIDATION_FAILED 는 다시 보내도 같은 결과라 다시 시도를 주지 않습니다. */
const isRetryable = (error: unknown) => !(error instanceof ApiError && (error.status === 404 || error.status === 422));

type RecommendationFeedbackActionsProps = {
  item: RecommendationItem;
  run: RecommendationRun;
  /** 저장 후 다시 조회한 추천 결과를 목록에 반영합니다 (RecommendationsPage.renderItemActions 의 onRunChange). */
  onRunChange: (run: RecommendationRun) => void;
};

/**
 * 추천 카드의 설명 보기·피드백 버튼 (T48, F-018 / FR-ANL-004).
 * - 관심 있음(liked)·관심 없음(not_interested)은 눌림 상태(aria-pressed)를 가진 토글입니다.
 *   눌린 버튼을 다시 누르거나 "피드백 취소"를 누르면 cleared 를 보내 정정합니다.
 * - 저장 중에는 버튼을 막아 중복 전송을 막고, 저장 후 GET /recommendation-runs/{id} 로 다시 조회해 저장된 상태를 보여줍니다.
 *   재조회만 실패하면 저장 응답으로 화면을 맞춥니다.
 * - 저장 실패: 5xx·네트워크 오류는 다시 시도를 주고, 404·422 는 다시 보내도 실패하므로 새 추천을 받도록 안내만 합니다.
 * - 피드백은 내 다음 추천을 개선하는 데에만 씁니다.
 */
export function RecommendationFeedbackActions({ item, run, onRunChange }: RecommendationFeedbackActionsProps) {
  const { recommendations } = useApi();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pending, setPending] = useState<RecommendationFeedbackChoice | null>(null);
  const [failed, setFailed] = useState<FeedbackFailure | null>(null);
  const [message, setMessage] = useState('');
  // 상태 갱신 전에 빠르게 두 번 눌러도 한 번만 보내도록 ref 로도 막습니다.
  const inFlight = useRef(false);
  const explainRef = useRef<HTMLButtonElement>(null);

  const posting = item.job_posting;
  const current = item.feedback;

  const submit = async (choice: RecommendationFeedbackChoice) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(choice);
    setFailed(null);
    setMessage('');
    try {
      const saved = await recommendations.sendFeedback({
        recommendation_run_id: run.recommendation_run_id,
        job_posting_id: posting.job_posting_id,
        feedback: choice,
      });
      let next: RecommendationRun;
      try {
        next = await recommendations.get(run.recommendation_run_id);
      } catch {
        next = applyFeedbackToRun(run, saved);
      }
      onRunChange(next);
      setMessage(savedMessages[saved.feedback]);
    } catch (error) {
      setFailed({ choice, retryable: isRetryable(error) });
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  };

  const toggle = (choice: RecommendationFeedbackValue) => void submit(current === choice ? 'cleared' : choice);

  return (
    <div className="recommendation-feedback-actions">
      {/* 공통 Button 은 ref 를 받지 않으므로 같은 클래스로 직접 그립니다(닫힌 뒤 초점 복귀용). */}
      <button
        ref={explainRef}
        type="button"
        className="ui-button ui-button--outline"
        aria-haspopup="dialog"
        aria-label={`${posting.title} 추천 설명 보기`}
        onClick={() => setDialogOpen(true)}
      >
        추천 설명 보기
      </button>

      <div className="recommendation-feedback-buttons" role="group" aria-label={`${posting.title} 피드백`} aria-busy={pending !== null}>
        {choices.map((choice) => (
          <button
            key={choice}
            type="button"
            className="recommendation-feedback-toggle"
            aria-pressed={current === choice}
            disabled={pending !== null}
            onClick={() => toggle(choice)}
          >
            {current === choice && <span aria-hidden="true">✓ </span>}
            {feedbackButtonLabels[choice]}
          </button>
        ))}
        {current !== null && (
          <button type="button" className="recommendation-feedback-clear" disabled={pending !== null} onClick={() => void submit('cleared')}>
            피드백 취소
          </button>
        )}
      </div>

      <p className="recommendation-feedback-status" role="status" aria-live="polite">
        {pending !== null ? '피드백을 저장하는 중입니다…' : message}
      </p>

      {failed !== null && (
        <div className="recommendation-feedback-error" role="alert">
          {failed.retryable ? (
            <>
              <span>피드백을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.</span>
              <button
                type="button"
                className="recommendation-feedback-retry"
                onClick={() => void submit(failed.choice)}
                disabled={pending !== null}
              >
                다시 시도
              </button>
            </>
          ) : (
            <span>이 공고에는 피드백을 남길 수 없습니다. 추천을 새로 받아 주세요.</span>
          )}
        </div>
      )}

      <p className="recommendation-feedback-note">{FEEDBACK_USAGE_NOTE}</p>

      {dialogOpen && (
        <RecommendationExplanationDialog
          item={item}
          run={run}
          onClose={() => setDialogOpen(false)}
          returnFocusRef={explainRef}
        />
      )}
    </div>
  );
}
