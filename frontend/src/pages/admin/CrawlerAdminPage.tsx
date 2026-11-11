import { useRef, useState, type KeyboardEvent } from 'react';
import { CommandsPanel, JobsPanel, KeywordsPanel, RunsPanel, SettingsPanel } from './CrawlerAdminPanels';
import './CrawlerAdmin.css';

const TABS = [
  { id: 'keywords', label: '검색어' },
  { id: 'jobs', label: '작업' },
  { id: 'runs', label: '실행 이력' },
  { id: 'settings', label: '스케줄 설정' },
  { id: 'commands', label: '명령 기록' },
] as const;
type TabId = (typeof TABS)[number]['id'];

/**
 * UI 크롤러 관리자 콘솔 (T156). admin 전용 경로(/admin/crawler), 기능 플래그 VITE_CRAWLER_ADMIN_UI 기본 꺼짐.
 * - 데이터: T155 읽기 API(#124) + 쓰기 API(#233, 서버 플래그 꺼지면 404 → 읽기 전용 안내)
 * - LIVE(실제 사이트) 수집 버튼은 없습니다. 실행은 Fixture 대기 작업 생성만 합니다.
 * - 탭: WAI-ARIA tabs 패턴(←/→/Home/End, 선택 탭만 Tab 순서에 포함)
 */
export function CrawlerAdminPage() {
  const [tab, setTab] = useState<TabId>('keywords');
  const [jobKeyword, setJobKeyword] = useState<number | undefined>(undefined);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function select(id: TabId, focus = false) {
    setTab(id);
    if (focus) tabRefs.current[id]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = TABS.findIndex((t) => t.id === tab);
    const next = event.key === 'ArrowRight' ? (index + 1) % TABS.length
      : event.key === 'ArrowLeft' ? (index - 1 + TABS.length) % TABS.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    select(TABS[next]!.id, true);
  }

  return (
    <section className="crawler-page" aria-labelledby="crawler-title">
      <h1 id="crawler-title">크롤러 관리</h1>
      <div className="crawler-notice" role="note">
        <p><strong>Fixture(합성 데이터) 전용입니다.</strong> 실제 사이트 수집(LIVE)은 승인 전이라 실행할 수 없습니다.</p>
        <p>실행 버튼은 대기(PENDING) 작업만 만듭니다. Worker·스케줄러를 바로 켜지 않으며, 스케줄 활성화는 별도 승인이 필요합니다.</p>
        <p>원본 HTML·수집 대상 URL·승인 정보는 이 화면과 API 응답에 나오지 않습니다.</p>
      </div>

      <div className="crawler-tabs" role="tablist" aria-label="크롤러 관리 영역" onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" id={`crawler-tab-${t.id}`}
            aria-selected={tab === t.id} aria-controls={`crawler-panel-${t.id}`} tabIndex={tab === t.id ? 0 : -1}
            ref={(el) => { tabRefs.current[t.id] = el; }} onClick={() => select(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`crawler-panel-${tab}`} aria-labelledby={`crawler-tab-${tab}`} className="crawler-panel">
        {tab === 'keywords' && <KeywordsPanel onShowJobs={(id) => { setJobKeyword(id); select('jobs'); }} />}
        {tab === 'jobs' && <JobsPanel keywordId={jobKeyword} onClearKeyword={() => setJobKeyword(undefined)} />}
        {tab === 'runs' && <RunsPanel />}
        {tab === 'settings' && <SettingsPanel />}
        {tab === 'commands' && <CommandsPanel />}
      </div>
    </section>
  );
}
