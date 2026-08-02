import { describe, expect, it } from "vitest";

import { countsTowardToday, dueInfo, isOverdue } from "./dueDate";
import { localMidnightUtc } from "../../../lib/quickParse";

const NY = "America/New_York";
const TODAY = "2026-07-15"; // what the server marked is_today

/** A to-do due at local midnight of `date` in `tz` — the backend's encoding. */
function todo(date: string | null, tz = NY) {
  return {
    id: "a1", type: "follow_up", title: "x", status: "pending",
    auto_generated: false, snooze_count: 0, created_at: "", updated_at: "",
    due_at: date === null ? null : localMidnightUtc(date, tz),
  } as never;
}

describe("the day boundary is the workspace's, not the browser's", () => {
  it("reads a due date in the workspace zone", () => {
    expect(dueInfo(todo(TODAY), NY, TODAY)).toEqual({ today: true, days: 0, warn: true });
    expect(dueInfo(todo("2026-07-16"), NY, TODAY)).toEqual({ today: false, days: 1, warn: true });
    expect(dueInfo(todo("2026-07-20"), NY, TODAY)).toEqual({ today: false, days: 5, warn: false });
  });

  it("puts an overdue item on today, warned", () => {
    // Overdue work is owed today — the same fold the capacity bar and the strip
    // both apply, which is why all three have to agree about the boundary.
    expect(dueInfo(todo("2026-07-10"), NY, TODAY)).toEqual({ today: true, days: 0, warn: true });
  });

  it("does not shift a day when the viewer is in another zone", () => {
    // The regression this replaces: the browser used to decide both sides. A
    // to-do due at NY local midnight on the 16th read as "today" from Tokyo on
    // the evening of the 15th, so it landed in the capacity bar a day early.
    // The zone here is the workspace's, so the answer cannot depend on where
    // the user is sitting.
    const due16 = todo("2026-07-16");
    expect(dueInfo(due16, NY, TODAY)?.today).toBe(false);
    expect(countsTowardToday(due16, NY, TODAY)).toBe(false);
  });

  it("counts calendar days, not 24-hour blocks, across a DST change", () => {
    // 2026-03-08 is 23 hours long in New York. Dividing elapsed milliseconds
    // would give 0.958 of a day and round to the neighbouring answer.
    expect(dueInfo(todo("2026-03-09"), NY, "2026-03-08")).toEqual({ today: false, days: 1, warn: true });
    expect(dueInfo(todo("2026-03-08"), NY, "2026-03-07")).toEqual({ today: false, days: 1, warn: true });
  });

  it("works in a half-hour zone", () => {
    const IN = "Asia/Kolkata";
    expect(dueInfo(todo(TODAY, IN), IN, TODAY)?.today).toBe(true);
    expect(dueInfo(todo("2026-07-16", IN), IN, TODAY)?.today).toBe(false);
  });
});

describe("what today is on the hook for", () => {
  it("includes undated work without needing a clock at all", () => {
    expect(countsTowardToday(todo(null), null, null)).toBe(true);
    expect(countsTowardToday(todo(null), NY, TODAY)).toBe(true);
  });

  it("excludes a DATED item while the zone is still unknown", () => {
    // The trap: dueInfo returns null both for "no date" and for "no zone yet".
    // Treating that null as "counts" would sweep every dated to-do into today
    // during load, inflating the capacity bar and the morning commitment with
    // work that is not due for a fortnight.
    const nextWeek = todo("2026-07-22");
    expect(countsTowardToday(nextWeek, null, TODAY)).toBe(false);
    expect(countsTowardToday(nextWeek, NY, null)).toBe(false);
    expect(countsTowardToday(nextWeek, NY, TODAY)).toBe(false);
    expect(countsTowardToday(todo(TODAY), NY, TODAY)).toBe(true);
  });
});

describe("overdue", () => {
  it("is strictly before today in the workspace calendar", () => {
    expect(isOverdue(todo("2026-07-14"), NY, TODAY)).toBe(true);
    expect(isOverdue(todo(TODAY), NY, TODAY)).toBe(false);
    expect(isOverdue(todo("2026-07-16"), NY, TODAY)).toBe(false);
  });

  it("is not claimed for undated work or before the zone is known", () => {
    expect(isOverdue(todo(null), NY, TODAY)).toBe(false);
    expect(isOverdue(todo("2026-07-14"), null, TODAY)).toBe(false);
    expect(isOverdue(todo("2026-07-14"), NY, null)).toBe(false);
  });
});
