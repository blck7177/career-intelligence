// What the morning ritual has to decide about, before it asks anything.
//
// The wizard's first step is about yesterday's leftovers, and it was always
// shown — including on the mornings when there were none, where it renders
// "Nothing carried over. Clean slate." and the only thing to do is press Next.
// A ritual that opens by asking a question with no content is a ritual people
// stop running. These functions decide which of the three real situations the
// day is in, and where the wizard should therefore start.
//
// Pure and dependency-free so they can be tested: the states are cheap to get
// wrong in a way that looks right in the one state the author happened to be in.

/**
 * The three shapes a morning can have — plus the one where we cannot tell yet.
 *
 * `unknown` is not a fourth situation, it is the absence of an answer, and it
 * exists because the counts are not equally trustworthy. `overdue` is derived
 * with isOverdue(), which reports false for EVERY to-do while the workspace
 * timezone or the server's date is still missing (it refuses to fall back to
 * the browser clock). So an overdue count of zero means "nothing carried over"
 * only once the calendar is known; before that it means nothing at all, and
 * skipping the leftovers step on the strength of it would skip a step that has
 * content — silently, on exactly the mornings a settings request failed.
 */
export type RitualPlate = "carry" | "today" | "empty" | "unknown";

/**
 * @param overdueCount  to-dos due before today and still open
 * @param plateCount    to-dos today is on the hook for (what the cap governs,
 *                      and what the wizard opens with — NOT the whole visible
 *                      horizon, which runs 14 days out)
 * @param calendarKnown workspace timezone AND the server's today are both in
 */
export function ritualPlate(
  overdueCount: number,
  plateCount: number,
  calendarKnown: boolean,
): RitualPlate {
  if (!calendarKnown) return "unknown";
  // Overdue work is a subset of what counts toward today, so these three are
  // mutually exclusive and cover every case: an empty plate already implies
  // nothing carried over.
  if (overdueCount > 0) return "carry";
  if (plateCount > 0) return "today";
  return "empty";
}

/** The first step with anything in it. */
export function ritualFirstStep(plate: RitualPlate): 1 | 2 {
  // "unknown" starts at 1 for the same reason it exists: not knowing whether
  // there are leftovers is a reason to ask, not a reason to skip.
  return plate === "carry" || plate === "unknown" ? 1 : 2;
}

/**
 * The steps actually reachable this morning.
 *
 * The dots are drawn from this rather than from a literal [1, 2, 3]. Three dots
 * above a two-step flow is a progress indicator that lies about how much is
 * left, and the first one can never be filled.
 */
export function ritualSteps(firstStep: 1 | 2): number[] {
  return [1, 2, 3].filter((s) => s >= firstStep);
}

// --- pulling work in from the queue (step 2) --------------------------------

/** The fields the queue offer reads off an application. */
export type QueueRow = {
  id: string;
  fit_score?: number | null;
  excitement?: number | null;
  job?: { posted_at?: string | null } | null;
};

/** The fields it reads off a to-do. Structural, so ActionRead needs no adapter. */
type Todo = { type: string; application_id?: string | null };

/**
 * Applications the ritual may offer to pull into today, best first.
 *
 * Ordered by the queue's own ranking so the wizard and the sidebar cannot
 * disagree about what is at the top, and filtered by what already has an apply
 * to-do — offering a row you already agreed to do is how the list stops being
 * believable.
 *
 * `actions` MUST be the unfiltered planner list, not the subset that counts
 * toward today. The Today list is server-side pending-only over a fourteen-day
 * horizon; narrowing it to today's plate would re-offer everything whose apply
 * to-do is dated tomorrow. It also must not be ApplicationRead.next_action_type,
 * which looks authoritative and is not: it is a single-slot summary that reports
 * the EARLIEST to-do and drops undated ones entirely, so an application with a
 * pending apply and an earlier prep reports "prep", and an undated apply — the
 * shape quick-add produces — is invisible to it.
 *
 * Three gaps this deliberately does not close, because each needs a decision
 * rather than a filter:
 *   1. a pending apply to-do dated beyond the fourteen-day horizon (reachable by
 *      repeated snoozing) is not seen, so its application can be re-offered;
 *   2. a COMPLETED apply to-do does not exclude anything — completing one does
 *      not move the application out of `planned`, so it returns to the queue;
 *   3. neither does a dismissed one.
 * All three fail toward offering again, which is the visible direction.
 */
export function offerableQueue<T extends QueueRow>(
  planned: T[],
  actions: Todo[],
  rank: (rows: T[]) => string[],
): T[] {
  // Annotated Set<string> and flatMap rather than filter+cast: a global to-do
  // (queue_refill) carries application_id === null, and `as string` would let
  // that null into the set silently. This way dropping the null check is a type
  // error, which is a better guard than a test — a test for it cannot fail,
  // because a null in the set matches no real id anyway.
  const covered = new Set<string>(
    actions.flatMap((a) => (a.type === "apply" && a.application_id ? [a.application_id] : [])),
  );
  const byId = new Map(planned.map((a) => [a.id, a]));
  return rank(planned)
    .filter((id) => !covered.has(id))
    .map((id) => byId.get(id))
    .filter((a): a is T => a !== undefined);
}

/**
 * The ids to file as today's commitment.
 *
 * Kept work plus whatever was just created, deduplicated and order-preserving.
 * Separate from the caller so that the ONE rule it encodes is testable: nothing
 * reaches this list that is not a real, server-assigned action id. The commit
 * endpoint totals estimates by matching ids against rows that exist and scores
 * an unknown id as zero WITHOUT complaining — its docstring says so — which
 * means a placeholder id here does not fail, it just quietly files a day worth
 * sixty minutes less per row, with nothing on screen to show for it.
 */
export function mergeCommitIds(keptIds: string[], createdIds: string[]): string[] {
  return [...new Set([...keptIds, ...createdIds])];
}
