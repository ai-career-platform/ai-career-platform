import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { RecommendationItem } from '../api/recommendations';
import { RecommendationCard } from './RecommendationCard';

// 가상 공고 데이터 (실제 기업·개인정보 아님)
const item = (overrides: Partial<RecommendationItem['job_posting']>): RecommendationItem => ({
  rank: 1,
  score: 70,
  reason: '목표 직무와 일치합니다.',
  feedback: null,
  job_posting: {
    job_posting_id: '00000000-0000-4000-8000-000000000199',
    title: '테스트 공고',
    status: 'published',
    company: { company_id: '00000000-0000-4000-8000-000000000299', name: '예시 회사' },
    job_role: null,
    employment_type: null,
    location_text: null,
    published_at: '2026-11-01T00:00:00Z',
    expires_at: null,
    ...overrides,
  },
});

const renderCard = (value: RecommendationItem) =>
  render(
    <MemoryRouter>
      <RecommendationCard item={value} personalized />
    </MemoryRouter>,
  );

describe('RecommendationCard', () => {
  it('shows employment type and closed marker as 공고 정보, not 관련 기술', () => {
    renderCard(item({ employment_type: 'contract', status: 'closed' }));
    const info = screen.getByRole('list', { name: '공고 정보' });
    expect(info).toHaveTextContent('계약직');
    expect(info).toHaveTextContent('마감');
    expect(screen.queryByRole('list', { name: '관련 기술' })).not.toBeInTheDocument();
  });

  it('renders no empty labelled list when there is no employment type and the posting is open', () => {
    renderCard(item({}));
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });
});
