import { describe, expect, it } from "vitest";
import {
  mergeCommitIds,
  offerableQueue,
  ritualFirstStep,
  ritualPlate,
  ritualSteps,
  type RitualPlate,
} from "./ritual";
import { rankedIds } from "./queueRank";

describe("ritualPlate", () => {
  it("reports carry whenever anything is overdue", () => {
    expect(ritualPlate(1, 5, true)).toBe("carry");
    // Overdue work counts toward today, so the plate can never be smaller than
    // the carry — but the state must not depend on that arithmetic holding.
    expect(ritualPlate(3, 3, true)).toBe("carry");
  });

  it("reports today when the plate has work but none of it is late", () => {
    expect(ritualPlate(0, 4, true)).toBe("today");
  });

  it("reports empty only when there is nothing on the plate at all", () => {
    expect(ritualPlate(0, 0, true)).toBe("empty");
  });

  it("refuses to answer until the calendar is known", () => {
    // The trap this exists for: isOverdue() reports false for every to-do while
    // the timezone or the server date is missing, so (0, 0) is indistinguishable
    // from a genuinely clear morning — and a settings request that failed would
    // silently produce a wizard that skips the leftovers it could not see.
    expect(ritualPlate(0, 0, false)).toBe("unknown");
    expect(ritualPlate(0, 9, false)).toBe("unknown");
    expect(ritualPlate(4, 9, false)).toBe("unknown");
  });

  it("covers every input — the three known states are exhaustive", () => {
    const seen = new Set<RitualPlate>();
    for (const overdue of [0, 1, 7]) {
      for (const plate of [0, 1, 7]) {
        if (overdue > plate) continue; // overdue ⊂ plate; not a reachable input
        seen.add(ritualPlate(overdue, plate, true));
      }
    }
    expect(seen).toEqual(new Set(["carry", "today", "empty"]));
  });
});

describe("ritualFirstStep", () => {
  it("opens on the leftovers only when there are leftovers", () => {
    expect(ritualFirstStep("carry")).toBe(1);
    expect(ritualFirstStep("today")).toBe(2);
    expect(ritualFirstStep("empty")).toBe(2);
  });

  it("opens on the leftovers when it cannot tell", () => {
    // Not knowing is a reason to ask, not a reason to skip. Reversing this is
    // the one change here that would be invisible in normal use: it only bites
    // when the settings request fails, which is never on a developer's machine.
    expect(ritualFirstStep("unknown")).toBe(1);
  });
});

describe("ritualSteps", () => {
  it("draws one dot per reachable step", () => {
    expect(ritualSteps(1)).toEqual([1, 2, 3]);
    expect(ritualSteps(2)).toEqual([2, 3]);
  });

  it("always ends on the confirm step", () => {
    for (const first of [1, 2] as const) {
      const steps = ritualSteps(first);
      expect(steps[0]).toBe(first);
      expect(steps[steps.length - 1]).toBe(3);
    }
  });
});

describe("offerableQueue", () => {
  const app = (id: string, over: Record<string, unknown> = {}) => ({
    id,
    fit_score: 50,
    excitement: 0,
    job: { posted_at: null },
    ...over,
  });
  // The real ranking, not a stub: the point of taking `rank` as a parameter is
  // that the wizard and the sidebar share one, so a test with its own ordering
  // would pass while they disagreed on screen.
  const rank = (rows: ReturnType<typeof app>[]) => rankedIds(rows, 3, Date.parse("2026-07-15"));

  it("offers the queue in the queue's order", () => {
    const rows = [app("low", { fit_score: 10 }), app("high", { fit_score: 90 })];
    expect(offerableQueue(rows, [], rank).map((a) => a.id)).toEqual(["high", "low"]);
  });

  it("drops applications that already have an apply to-do", () => {
    const rows = [app("a"), app("b")];
    const out = offerableQueue(rows, [{ type: "apply", application_id: "a" }], rank);
    expect(out.map((r) => r.id)).toEqual(["b"]);
  });

  it("only apply to-dos exclude — another kind of to-do is other work", () => {
    // A follow-up or a note about an application says nothing about whether you
    // have agreed to apply to it.
    const rows = [app("a")];
    for (const type of ["follow_up", "prep", "thank_you", "custom", "networking"]) {
      expect(offerableQueue(rows, [{ type, application_id: "a" }], rank)).toHaveLength(1);
    }
  });

  it("ignores a global to-do, which belongs to no application", () => {
    // queue_refill actions carry application_id === null. Recorded rather than
    // guarded: this assertion CANNOT fail, because a null in the covered set
    // matches no real id whether or not the null check is there. What actually
    // forbids the null is the Set<string> annotation in offerableQueue, and tsc
    // enforces that. Kept because the behaviour is worth stating; not counted as
    // coverage.
    const rows = [app("a"), app("b")];
    expect(offerableQueue(rows, [{ type: "apply", application_id: null }], rank)).toHaveLength(2);
  });

  it("returns nothing rather than undefined holes when everything is covered", () => {
    const rows = [app("a")];
    expect(offerableQueue(rows, [{ type: "apply", application_id: "a" }], rank)).toEqual([]);
  });
});

describe("mergeCommitIds", () => {
  it("keeps both halves, kept work first", () => {
    expect(mergeCommitIds(["k1", "k2"], ["n1"])).toEqual(["k1", "k2", "n1"]);
  });

  it("deduplicates", () => {
    // Not hypothetical: a retried commit after a partial failure re-sends ids
    // that were created on the first attempt.
    expect(mergeCommitIds(["a"], ["a", "b"])).toEqual(["a", "b"]);
  });

  it("survives either half being empty", () => {
    expect(mergeCommitIds([], ["n"])).toEqual(["n"]);
    expect(mergeCommitIds(["k"], [])).toEqual(["k"]);
  });
});
