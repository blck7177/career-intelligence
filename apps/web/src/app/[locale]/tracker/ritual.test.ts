import { describe, expect, it } from "vitest";
import { ritualFirstStep, ritualPlate, ritualSteps, type RitualPlate } from "./ritual";

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
