import { createContext, useContext } from 'react';

// T156: route-level feature flag shared with the layout menu.
// Default false prevents exposing the navigation outside approved routes.
// Kept apart from the Provider component so the component file only exports components (react-refresh lint).
export const CrawlerNavigationContext = createContext(false);

export function useCrawlerNavigationEnabled(): boolean {
  return useContext(CrawlerNavigationContext);
}
