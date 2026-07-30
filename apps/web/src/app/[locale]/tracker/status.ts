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
