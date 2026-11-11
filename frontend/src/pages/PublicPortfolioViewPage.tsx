/**
 * 공개 포트폴리오 보기 `/p/:token` (T130). 로그인 없이 열립니다.
 * - 검색엔진 비노출: `<meta name="robots" content="noindex, nofollow, noarchive">`(서버도 X-Robots-Tag, T129).
 * - 만료·회수·공개 중단·없는 링크는 한 문구로 안내합니다(서버가 구분하지 않음 — 추측 방지).
 */
import { useEffect } from 'react';
import { useParams } from 'react-router';
import { useQuery } from '../api/useQuery';
import { usePortfolioReader } from '../portfolio/portfolioContext';
import { PublicProfileView } from '../portfolio/PublicProfileView';
import { StatePanel } from '../components/StatePanel';
import './PublicPortfolio.css';

function useNoIndex() {
  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex, nofollow, noarchive';
    const referrer = document.createElement('meta');
    referrer.name = 'referrer';
    referrer.content = 'no-referrer';
    document.head.append(meta, referrer);
    return () => { meta.remove(); referrer.remove(); };
  }, []);
}

export function PublicPortfolioViewPage() {
  useNoIndex();
  const { token = '' } = useParams();
  const reader = usePortfolioReader();
  const view = useQuery(['public-portfolio', token], (signal) => reader.view(token, signal));
  return (
    <section className="portfolio-page" aria-labelledby="public-portfolio-title">
      <h1 id="public-portfolio-title">공개 포트폴리오</h1>
      {(view.status === 'loading' || view.status === 'idle') && <StatePanel variant="loading" title="불러오는 중입니다" />}
      {view.status === 'error' && (
        <StatePanel variant="error" title="볼 수 없는 링크입니다"
          description="링크가 만료되었거나, 회수되었거나, 공개가 중단되었거나, 잘못된 주소입니다." />
      )}
      {view.status === 'ready' && (
        <>
          <PublicProfileView profile={view.data} />
          {view.data.shared_until && (
            <p className="portfolio-muted">이 링크는 {new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeZone: 'Asia/Seoul' })
              .format(new Date(view.data.shared_until))}까지 열립니다. 본인이 공유한 범위만 보입니다.</p>
          )}
        </>
      )}
    </section>
  );
}
