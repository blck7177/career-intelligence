import { describe, expect, it } from "vitest";

import {
  DEFAULT_END, DEFAULT_START, SLOT, SLOT_H,
  bandFor, fmtClock, geometryFor, menuPlacement, minutesOfDay, mondayOf, monthGrid, rowsFor, shiftMonth, snapDuration,
} from "./scheduleGrid";

const NY = "America/New_York";

describe("the visible band", () => {
  it("is the mockup's 09:00–18:00 for an ordinary week", () => {
    expect(bandFor([])).toEqual({ start: 9 * 60, end: 18 * 60 });
    expect(bandFor([{ start: 10 * 60, duration: 60 }])).toEqual({ start: 9 * 60, end: 18 * 60 });
    expect(rowsFor(bandFor([]))).toHaveLength(18);
  });

  it("stretches for an early call instead of drawing it on the wrong line", () => {
    // The mockup clamps this to the 09:00 row while the block's own label still
    // reads 08:00 — a picture that looks right and is not.
    const band = bandFor([{ start: 8 * 60, duration: 45 }]);
    expect(band.start).toBe(8 * 60);
    expect(geometryFor({ start: 8 * 60, duration: 45 }, band)!.top).toBe(0);
  });

  it("stretches for a round that runs past the end of the day", () => {
    const band = bandFor([{ start: 17 * 60, duration: 180 }]); // 17:00–20:00
    expect(band.end).toBe(20 * 60);
  });

  it("snaps a ragged edge out to a whole slot", () => {
    // 08:10 must not produce a half-height first row.
    expect(bandFor([{ start: 8 * 60 + 10, duration: 30 }]).start).toBe(8 * 60);
    expect(bandFor([{ start: 17 * 60, duration: 35 }]).end).toBe(18 * 60);
  });

  it("treats an unknown duration as one slot, not as zero or forever", () => {
    expect(bandFor([{ start: 19 * 60, duration: null }]).end).toBe(19 * 60 + SLOT);
  });

  it("cannot be talked into an absurd number of rows", () => {
    // A malformed instant is upstream's problem; it must not become 40,000 DOM
    // nodes here.
    const band = bandFor([{ start: -5000, duration: 999999 }]);
    expect(band.start).toBeGreaterThanOrEqual(0);
    expect(band.end).toBeLessThanOrEqual(24 * 60);
  });
});

describe("block geometry", () => {
  const band = { start: DEFAULT_START, end: DEFAULT_END };

  it("puts a block at the row its start time belongs to", () => {
    expect(geometryFor({ start: 9 * 60, duration: 30 }, band)!.top).toBe(0);
    expect(geometryFor({ start: 10 * 60, duration: 30 }, band)!.top).toBe(2 * SLOT_H);
    expect(geometryFor({ start: 9 * 60 + 30, duration: 30 }, band)!.top).toBe(SLOT_H);
  });

  it("is as tall as the time it takes, less the seam", () => {
    // The mockup's dur/SLOT*SLOT_H-4. The -4 is the gap between stacked blocks.
    expect(geometryFor({ start: 9 * 60, duration: 30 }, band)!.height).toBe(30);
    expect(geometryFor({ start: 9 * 60, duration: 60 }, band)!.height).toBe(64);
    expect(geometryFor({ start: 9 * 60, duration: 120 }, band)!.height).toBe(132);
  });

  it("never spills past the end of the band onto the day footer", () => {
    const g = geometryFor({ start: 17 * 60 + 30, duration: 120 }, band)!;
    expect(g.top + g.height).toBeLessThanOrEqual((DEFAULT_END - DEFAULT_START) / SLOT * SLOT_H);
  });

  it("returns nothing for a block outside the band rather than pinning it", () => {
    // Pinning is the mockup's behaviour and the reason bandFor exists. If one
    // ever gets here, drawing it in the wrong place would hide the real fault.
    expect(geometryFor({ start: 8 * 60, duration: 30 }, band)).toBeNull();
    expect(geometryFor({ start: 18 * 60, duration: 30 }, band)).toBeNull();
  });

  it("gives an unknown-length block one readable slot", () => {
    expect(geometryFor({ start: 9 * 60, duration: null }, band)!.height).toBe(SLOT_H - 4);
  });
});

describe("drop duration", () => {
  it.each([
    [15, 30], [20, 30], [30, 30], [45, 60], [60, 60], [90, 90], [5, 30],
  ])("an estimate of %i minutes occupies %i", (est, occupied) => {
    expect(snapDuration(est)).toBe(occupied);
  });
});

describe("reading the clock in the workspace zone", () => {
  it("uses the workspace zone, not the runner's", () => {
    // 13:30Z is 09:30 in New York.
    expect(minutesOfDay("2026-08-05T13:30:00Z", NY)).toBe(9 * 60 + 30);
    expect(minutesOfDay("2026-08-05T13:30:00Z", "UTC")).toBe(13 * 60 + 30);
  });

  it("reads midnight as 0, not 1440", () => {
    expect(minutesOfDay("2026-08-05T04:00:00Z", NY)).toBe(0);
  });

  it("survives a half-hour zone", () => {
    expect(minutesOfDay("2026-08-05T04:00:00Z", "Asia/Kolkata")).toBe(9 * 60 + 30);
  });
});

describe("axis labels", () => {
  it.each([[9 * 60, "9:00"], [9 * 60 + 30, "9:30"], [18 * 60, "18:00"]])("%i → %s", (m, s) => {
    expect(fmtClock(m)).toBe(s);
  });
});

describe("the month grid behind the week picker", () => {
  it("folds any day to the Monday of its week", () => {
    expect(mondayOf("2026-08-01")).toBe("2026-07-27"); // a Saturday
    expect(mondayOf("2026-08-02")).toBe("2026-07-27"); // Sunday belongs to the week before
    expect(mondayOf("2026-08-03")).toBe("2026-08-03"); // Monday is its own
  });

  it("gives whole Mon..Sun rows, so every row is a week you can open", () => {
    const rows = monthGrid("2026-08-15");
    for (const r of rows) {
      expect(r).toHaveLength(7);
      expect(mondayOf(r[0])).toBe(r[0]);
    }
    // August 2026 starts on a Saturday, so the first row reaches back into July.
    expect(rows[0][0]).toBe("2026-07-27");
    expect(rows[0]).toContain("2026-08-01");
    // ...and the last row covers the 31st.
    expect(rows[rows.length - 1]).toContain("2026-08-31");
  });

  it("covers a month that starts on a Monday without an empty leading row", () => {
    const rows = monthGrid("2026-06-10"); // June 2026 starts Monday
    expect(rows[0][0]).toBe("2026-06-01");
  });

  it("does not lose a day across a year boundary", () => {
    const rows = monthGrid("2026-12-05");
    expect(rows[rows.length - 1].some((d) => d.startsWith("2027-01"))).toBe(true);
  });

  it("steps months without landing on a day that does not exist", () => {
    // 3/31 minus one month is February; clamping keeps it a real date rather
    // than rolling forward into March, which would make the arrow a no-op.
    expect(shiftMonth("2026-03-31", -1)).toBe("2026-02-28");
    expect(shiftMonth("2026-01-31", 1)).toBe("2026-02-28");
    expect(shiftMonth("2026-12-15", 1)).toBe("2027-01-15");
    expect(shiftMonth("2026-01-15", -1)).toBe("2025-12-15");
  });
});

describe("menuPlacement", () => {
  const VP = { width: 1500, height: 900 };
  const MENU = { width: 250, height: 160 };
  const cell = (over: Partial<{ left: number; top: number; right: number; bottom: number }> = {}) =>
    ({ left: 400, top: 300, right: 500, bottom: 334, ...over });

  it("opens to the right of the cell, clear of the slot being aimed at", () => {
    expect(menuPlacement(cell(), MENU, VP)).toEqual({ left: 506, top: 300 });
  });

  it("flips to the left rather than hanging off the right edge", () => {
    // Sunday, the last column — the one a week is most often planned from.
    const sunday = cell({ left: 1330, right: 1430 });
    const { left } = menuPlacement(sunday, MENU, VP);
    expect(left).toBe(1330 - 6 - 250);
    expect(left + MENU.width).toBeLessThanOrEqual(sunday.left);
  });

  it("slides up instead of running past the bottom", () => {
    const late = cell({ top: 820, bottom: 854 });
    expect(menuPlacement(late, MENU, VP).top).toBe(900 - 160 - 6);
  });

  it("never places the menu outside the viewport, from any cell", () => {
    for (const left of [0, 40, 700, 1300, 1480]) {
      for (const top of [0, 10, 450, 880]) {
        const { left: L, top: T } = menuPlacement(cell({ left, top, right: left + 100, bottom: top + 34 }), MENU, VP);
        expect(L).toBeGreaterThanOrEqual(6);
        expect(T).toBeGreaterThanOrEqual(6);
        expect(T + MENU.height).toBeLessThanOrEqual(VP.height);
      }
    }
  });

  it("pins to the gap when the menu is taller than the viewport", () => {
    // A short window with the picker listing many unscheduled items.
    expect(menuPlacement(cell(), { width: 250, height: 1200 }, VP).top).toBe(6);
  });
});
