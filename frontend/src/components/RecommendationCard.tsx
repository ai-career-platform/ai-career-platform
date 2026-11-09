import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { jobPostingDetailPath } from '../api/recommendations';
import type { EmploymentType, RecommendationItem } from '../api/recommendations';
import { JobCard, type CardTone, type JobCardData } from './JobCard';
import './RecommendationCard.css';

const tones: readonly CardTone[] = ['blue', 'purple', 'green', 'orange'];

const employmentLabels: Record<EmploymentType, string> = {
  full_time: '정규직',
  contract: '계약직',
  intern: '인턴',
  part_time: '파트타임',
};

const feedbackLabels = { liked: '좋아요 표시함', not_interested: '관심 없음 표시함' } as const;

/** 추천 항목의 공고 요약을 공통 JobCard 형태로 바꿉니다. tags 는 기술이 아닌 공고 정보(고용 형태·마감)라 '공고 정보' 목록으로 표시합니다. */
function toJobCard(item: RecommendationItem): JobCardData {
  const posting = item.job_posting;
  const tags = [
    posting.employment_type ? employmentLabels[posting.employment_type] : null,
    posting.status === 'closed' ? '마감' : null,
  ].filter((tag): tag is string => tag !== null);
  return {
    id: posting.job_posting_id,
    category: posting.job_role?.name ?? '직무 미지정',
    company: posting.company.name,
    initial: posting.company.name.slice(0, 1),
    title: posting.title,
    detail: posting.location_text ?? '근무지 정보 없음',
    tags,
    tone: tones[(item.rank - 1) % tones.length] ?? 'blue',
  };
}

type RecommendationCardProps = {
  item: RecommendationItem;
  /** 기준 추천(fallback)이면 개인화 점수 대신 안내를 보여줍니다. */
  personalized: boolean;
  /**
   * 카드 아래쪽 확장 영역. T48(추천 설명 모달·피드백 버튼)이 여기에 버튼을 넣습니다.
   * 피드백은 다음 추천 개선에만 쓰이며 기업에 제공되지 않습니다.
   */
  actions?: ReactNode;
};

export function RecommendationCard({ item, personalized, actions }: RecommendationCardProps) {
  const titleId = `recommendation-${item.job_posting.job_posting_id}`;
  return (
    <article className="recommendation-card" aria-labelledby={titleId}>
      <header className="recommendation-card-head">
        <h2 className="recommendation-rank" id={titleId}>
          {item.rank}위 · {item.job_posting.title}
        </h2>
        {item.score === null ? (
          <span className="recommendation-score recommendation-score--none">점수 없음</span>
        ) : (
          <span className="recommendation-score">
            <span aria-hidden="true">
              {item.score}
              <small>/100</small>
            </span>
            <span className="sr-only">적합 점수 100점 만점에 {item.score}점</span>
          </span>
        )}
      </header>

      <p className="recommendation-score-meaning">
        {item.score === null
          ? personalized
            ? '이 공고는 적합 점수를 계산하지 않았습니다.'
            : '기준 추천이라 개인 적합 점수를 계산하지 않았습니다.'
          : '적합 점수는 목표 직무·보유 기술이 공고 요구와 얼마나 맞는지 나타낸 0~100 참고 값이며, 합격 가능성(확률)이 아닙니다.'}
      </p>

      <JobCard job={toJobCard(item)} tagsLabel="공고 정보" />

      <div className="recommendation-reason">
        <p className="recommendation-reason-label">{personalized ? '추천 이유' : '표시 이유'}</p>
        <p>{item.reason}</p>
      </div>

      <footer className="recommendation-card-foot">
        {item.feedback && <span className="recommendation-feedback">{feedbackLabels[item.feedback]}</span>}
        <Link
          className="recommendation-detail-link"
          to={jobPostingDetailPath(item.job_posting.job_posting_id)}
          aria-label={`${item.job_posting.title} 공고 상세 보기`}
        >
          공고 상세 보기
        </Link>
        {actions && <div className="recommendation-actions">{actions}</div>}
      </footer>
    </article>
  );
}
