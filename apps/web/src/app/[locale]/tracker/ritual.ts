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
