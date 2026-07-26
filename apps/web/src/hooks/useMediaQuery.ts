"use client";

import { useEffect, useState } from "react";

/**
 * Subscribe to a CSS media query from client components.
 *
 * SSR / first client render return `false` (the query result is unknown until
 * the browser resolves it on mount). Callers that flip behavior on the result
 * — e.g. row click = select-in-pane on desktop vs. navigate on mobile — should
 * treat `false` as the safe fallback: before hydration a desktop row still
 * navigates to the full page, then upgrades to in-pane selection once mounted.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
