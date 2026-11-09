import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '../api/client';
import { CollectedJobsPreview } from './CollectedJobsPreview';
vi.mock('../api/client', () => ({ apiGet: vi.fn<typeof apiGet>() }));
const get = vi.mocked(apiGet);
const base = { location_text: null, employment_type: null, collected_at: '2026-01-01', company_name: '가상 기업' };
beforeEach(() => get.mockReset());
describe('isolated collected jobs preview', () => {
  it('separates HTTP and imported records, and only links trusted HTTPS sources', async () => {
    get.mockResolvedValueOnce([
      { ...base, external_posting_id: '1', source_code: 'jobkorea_live', evidence: 'live_http', title: '가상 HTTP 공고', source_url: 'https://www.jobkorea.co.kr/example' },
      { ...base, external_posting_id: '2', source_code: 'jobkorea_imported', evidence: 'imported_html', title: '가져온 가상 공고', source_url: 'javascript:alert(1)' },
      { ...base, external_posting_id: '3', source_code: 'jobkorea_live', evidence: 'imported_html', title: '불일치 기록', source_url: 'https://www.jobkorea.co.kr/example' },
    ]);
    render(<CollectedJobsPreview />);
    expect(await screen.findByText('가상 HTTP 공고')).toBeInTheDocument();
    expect(screen.queryByText('가져온 가상 공고')).not.toBeInTheDocument();
    expect(screen.queryByText('불일치 기록')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '잡코리아 원문 보기' })).toHaveAttribute('rel', 'noopener noreferrer');
    fireEvent.change(screen.getByLabelText('수집 구분'), { target: { value: 'imported_html' } });
    expect(screen.getByText('가져온 가상 공고')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '잡코리아 원문 보기' })).not.toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('/jobs/collected?limit=100', { mockEnabled: false });
  });
  it('handles errors and retry', async () => {
    get.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([]);
    render(<CollectedJobsPreview />);
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('해당 수집 기록이 없습니다.')).toBeInTheDocument();
  });
});
