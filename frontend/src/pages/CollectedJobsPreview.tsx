import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';

type CollectedJob = {
  external_posting_id: string;
  source_code: string;
  title: string;
  company_name: string;
  location_text: string | null;
  employment_type: string | null;
  source_url: string;
  collected_at: string;
  evidence: string;
};

function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && ['www.jobkorea.co.kr', 'jobkorea.co.kr'].includes(url.hostname)
      && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}

/** Local developer preview. This is not the formal T18 posting contract. */
export function CollectedJobsPreview() {
  const [items, setItems] = useState<CollectedJob[] | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [source, setSource] = useState<'live_http' | 'imported_html'>('live_http');
  useEffect(() => {
    let active = true;
    apiGet<CollectedJob[]>('/jobs/collected?limit=100', { mockEnabled: false }).then(
      data => { if (active) { setItems(data); setError(false); } },
      () => { if (active) setError(true); },
    );
    return () => { active = false; };
  }, [retry]);
  const shown = items?.filter(item => item.evidence === source &&
    item.source_code === (source === 'live_http' ? 'jobkorea_live' : 'jobkorea_imported')) ?? [];
  return <section className="t24-panel" aria-labelledby="collected-preview-title">
    <h2 id="collected-preview-title">수집 공고 개발 미리보기</h2>
    <p>수집 API의 최근 최대 100건 중 선택한 출처만 표시합니다. 실제 모집 상태와 서비스 표시 권한은 별도 확인이 필요합니다.</p>
    <label>수집 구분 <select value={source} onChange={e => setSource(e.target.value as 'live_http' | 'imported_html')}>
      <option value="live_http">HTTP 수집 기록</option><option value="imported_html">HTML 가져오기 기록</option>
    </select></label>
    {error ? <p role="alert">수집 공고를 불러오지 못했습니다. <button type="button" onClick={() => { setItems(null); setError(false); setRetry(n => n + 1); }}>다시 시도</button></p>
      : !items ? <p role="status">불러오는 중...</p> : shown.length === 0 ? <p>해당 수집 기록이 없습니다.</p> : <ul className="t24-posting-list">
        {shown.map(item => {
          const url = safeSourceUrl(item.source_url);
          return <li className="t24-posting" key={`${item.source_code}:${item.external_posting_id}`}>
            <strong>{item.title}</strong><span>{item.company_name}</span><span>지역: {item.location_text || '정보 없음'}</span>
            <span>수집 기록: {item.collected_at || '정보 없음'}</span>
            {url && <a href={url} target="_blank" rel="noopener noreferrer">잡코리아 원문 보기</a>}
          </li>;
        })}
      </ul>}
  </section>;
}
