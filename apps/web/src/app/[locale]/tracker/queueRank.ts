/** Anything the queue ranks — the fields it actually reads. */
type Rankable = {
  id: string;
  fit_score?: number | null;
  excitement?: number | null;
  job?: { posted_at?: string | null } | null;
};

/**
 * A posting is fresh when its true posting date is inside the window.
 *
 * Freshness needs a real posting date: the application's own age cannot stand
 * in for it, so an unknown posted_at is never fresh rather than optimistically
 * recent.
 */
export function isFresh(
  posted: string | null | undefined,
  windowDays: number,
  now: number = Date.now(),
): boolean {
  if (!posted) return false;
  const days = Math.floor((now - new Date(posted).getTime()) / 86400_000);
  return days >= 0 && days < windowDays;
}

/**
 * The queue's ranking: freshness dominates, then fit, then excitement.
 *
 * The weights are what make that ordering true rather than nominal — a fresh
 * posting outranks any stale one whatever its fit (1000 clears the 300 a
 * perfect fit can contribute), and three stars can lift a role past roughly 25
 * points of fit but not past freshness. Extracted so the sidebar and the
 * Pipeline queue rank identically; two copies of a formula like this drift the
 * first time one of them is tuned.
 */
export function queueScore(a: Rankable, freshDays: number, now: number = Date.now()): number {
  return (
    (isFresh(a.job?.posted_at, freshDays, now) ? 1000 : 0)
    + (a.fit_score ?? 0) * 3
    + (a.excitement ?? 0) * 25
  );
}

/**
 * Ids in ranked order.
 *
 * Returns ids, not rows, because callers snapshot the ORDER and keep editing
 * the rows: rating a row optimistically rewrites it, and a third star lifting
 * it past its neighbour mid-gesture means the next click lands on a different
 * application.
 */
export function rankedIds(rows: Rankable[], freshDays: number, now: number = Date.now()): string[] {
  return [...rows]
    .sort((a, b) => queueScore(b, freshDays, now) - queueScore(a, freshDays, now))
    .map((a) => a.id);
}
