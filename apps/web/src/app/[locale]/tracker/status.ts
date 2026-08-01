/** Status presentation + UI transition affordances for the tracker.
 *  The authoritative transition rules live in the backend
 *  (packages/domain/applications/transitions.py); these arrays only decide
 *  which buttons to *offer* — the API still validates every move. */

export const STATUS_STYLE: Record<string, { bg: string; fg: string }> = {
  planned: { bg: "var(--muted)", fg: "var(--ink-muted)" },
  applied: { bg: "var(--match-good-bg)", fg: "var(--match-good-fg)" },
  in_review: { bg: "var(--match-good-bg)", fg: "var(--match-good-fg)" },
  interviewing: { bg: "var(--match-strong-bg)", fg: "var(--match-strong-fg)" },
  offer: { bg: "var(--match-strong-bg)", fg: "var(--match-strong-fg)" },
  rejected: { bg: "var(--danger-bg)", fg: "var(--danger-fg)" },
  withdrawn: { bg: "var(--muted)", fg: "var(--ink-muted)" },
  ghosted: { bg: "var(--muted)", fg: "var(--ink-muted)" },
};

// Forward funnel moves offered from each live status.
export const FORWARD_NEXT: Record<string, string[]> = {
  planned: ["applied"],
  applied: ["in_review", "interviewing", "offer"],
  in_review: ["interviewing", "offer"],
  interviewing: ["offer"],
  offer: [],
  rejected: [],
  withdrawn: [],
  ghosted: [],
};

export const CLOSE_STATUSES = ["rejected", "withdrawn", "ghosted"];
export const LIVE_STATUSES = ["planned", "applied", "in_review", "interviewing", "offer"];

/** Minimum shape restoreTargetOf needs — a subset of ApplicationDetail, so the
 *  pure module stays free of the API client. */
type ClosedApplication = {
  status: string;
  events?: { event_type: string; payload_json?: Record<string, unknown> | null; created_at: string }[] | null;
};

/** Where a reopen should land: the status this application held immediately
 *  before it closed, read off the audit event that recorded the close.
 *
 *  Picked by max(created_at) rather than by position, so it does not depend on
 *  the endpoint's ordering (the events endpoint sorts ascending today; nothing
 *  in this file should care if that changes). A `from` that is itself a closed
 *  status is skipped — a forced ghosted -> rejected correction says nothing
 *  about where the application was actually alive.
 *
 *  Falls back to "applied" when no such event exists (rows closed before the
 *  events table, or an import that arrived closed). The button always names its
 *  target, so the fallback is something the user reads before clicking rather
 *  than a stage invented on their behalf. */
export function restoreTargetOf(app: ClosedApplication): string {
  let best: { at: number; from: string } | null = null;
  for (const e of app.events ?? []) {
    if (e.event_type !== "status_changed") continue;
    const p = (e.payload_json ?? {}) as { from?: unknown; to?: unknown };
    const from = typeof p.from === "string" ? p.from : null;
    if (p.to !== app.status || from === null || !LIVE_STATUSES.includes(from)) continue;
    const at = new Date(e.created_at).getTime();
    if (!Number.isFinite(at)) continue;
    if (best === null || at > best.at) best = { at, from };
  }
  return best?.from ?? "applied";
}

// A/B/C effort-tier lane chip styling. The b tier used to carry inline var()
// fallbacks because --warn-* did not exist yet, so only the fallback ever
// painted; the token is now defined in globals.css at those same values.
export const LANE_STYLE: Record<string, { bg: string; fg: string }> = {
  a: { bg: "var(--match-good-bg)", fg: "var(--match-good-fg)" },
  b: { bg: "var(--warn-bg)", fg: "var(--warn-fg)" },
  c: { bg: "var(--match-partial-bg)", fg: "var(--match-partial-fg)" },
};
// Lane cycle order for the detail editor: none -> A -> B -> C -> none.
export const LANE_CYCLE: (string | null)[] = [null, "a", "b", "c"];
