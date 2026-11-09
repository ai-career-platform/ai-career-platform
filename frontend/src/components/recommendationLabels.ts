import type {
  ModelKind,
  ModelVersionRef,
  RecommendationFeedbackValue,
  RecommendationRunStatus,
} from '../api/recommendations';

/** 추천 목록(UI-017)과 추천 설명 대화상자(T48)가 같이 쓰는 표시 문구 */
export const recommendationStatusLabels: Record<RecommendationRunStatus, string> = {
  completed: '맞춤 추천',
  fallback: '기준 추천 (개인화 아님)',
  failed: '추천 실패',
};

export const modelKindLabels: Record<ModelKind, string> = {
  rule: '규칙 기반',
  ml: '머신러닝 모델',
  llm: '언어 모델',
};

/** 계산 기준 표시: "match_rule v1 (규칙 기반)" */
export const formatModelVersion = (model: ModelVersionRef) =>
  `${model.model_code} v${model.version} (${modelKindLabels[model.kind]})`;

export const generatedAtFormat = new Intl.DateTimeFormat('ko-KR', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Asia/Seoul',
});

/** 피드백 버튼 이름 (liked = 관심 있음, not_interested = 관심 없음) */
export const feedbackButtonLabels: Record<RecommendationFeedbackValue, string> = {
  liked: '관심 있음',
  not_interested: '관심 없음',
};

/** 카드에 보이는 내 최신 피드백 */
export const feedbackStateLabels: Record<RecommendationFeedbackValue, string> = {
  liked: '관심 있음 표시함',
  not_interested: '관심 없음 표시함',
};

/** 피드백 용도 안내. 피드백은 내 다음 추천을 개선하는 데에만 씁니다. */
export const FEEDBACK_USAGE_NOTE = '피드백은 내 추천 개선에만 사용돼요.';
