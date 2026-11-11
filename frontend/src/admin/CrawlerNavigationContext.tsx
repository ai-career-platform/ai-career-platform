import { createContext, useContext, type ReactNode } from 'react';

// T156: route-level feature flag shared with the layout menu.
// Default false prevents exposing the navigation outside approved routes.
const CrawlerNavigationContext = createContext(false);

export function CrawlerNavigationProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  return <CrawlerNavigationContext.Provider value={enabled}>{children}</CrawlerNavigationContext.Provider>;
}

export function useCrawlerNavigationEnabled(): boolean {
  return useContext(CrawlerNavigationContext);
}
