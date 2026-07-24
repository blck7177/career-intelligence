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
  rejected: { bg: "#fee2e2", fg: "#991b1b" },
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
