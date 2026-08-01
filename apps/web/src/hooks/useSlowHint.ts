"use client";

import { useEffect, useState } from "react";

/**
 * True once `active` has been true for `afterMs` — for saying "this is taking a
 * while" without saying it on the fast path.
 *
 * Importing a job URL runs a synchronous three-tier fetch server-side (the ATS
 * JSON API, then the page over httpx, then Jina), each tier with its own 10s
 * timeout. A cached ATS hit returns in under a second; a slow careers page can
 * run for tens of seconds. A spinner is honest feedback for the first case and
 * looks like a hung page in the second, so the extra sentence has to appear on
 * elapsed time rather than being printed up front — a permanent "this may take
 * a while" trains people to ignore it, and this codebase has the same note
 * about confirmations that always show.
 */
export function useSlowHint(active: boolean, afterMs = 3000): boolean {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) {
      setSlow(false);
      return;
    }
    const id = setTimeout(() => setSlow(true), afterMs);
    return () => clearTimeout(id);
  }, [active, afterMs]);
  return slow;
}
