import type { ReactNode } from 'react';
import { CrawlerNavigationContext } from './crawlerNavigation';

export function CrawlerNavigationProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  return <CrawlerNavigationContext.Provider value={enabled}>{children}</CrawlerNavigationContext.Provider>;
}
