import { describe, expect, it } from "vitest";

import { dueAtFor, localMidnightUtc, localToday, parseQuickAdd } from "./quickParse";

const NY = "America/New_York";
// Wed 2026-07-15 16:00Z = 12:00 EDT, so "today" in New York is Wed 2026-07-15.
const NOW = new Date("2026-07-15T16:00:00Z");
const MON = new Date("2026-07-13T16:00:00Z");

/** Just the parts a caller acts on, so assertions read as intent. */
function p(input: string, opts = {}, now = NOW) {
  const r = parseQuickAdd(input, NY, opts, now);
  return { title: r.title, date: r.date?.date, min: r.duration?.minutes, type: r.type?.value };
}

describe("localToday", () => {
  it("reads the calendar date in the given zone, not the runner's", () => {
    expect(localToday(NY, NOW)).toBe("2026-07-15");
    // Same instant, already Thursday in Tokyo.
    expect(localToday("Asia/Tokyo", NOW)).toBe("2026-07-16");
  });
});

describe("relative dates", () => {
  it.each([
    ["call recruiter today", "2026-07-15", "call recruiter"],
    ["ping stripe tomorrow", "2026-07-16", "ping stripe"],
    ["ping tmr", "2026-07-16", "ping"],
    ["给 HM 写信 明天", "2026-07-16", "给 HM 写信"],
    ["复盘 后天", "2026-07-17", "复盘"],
  ])("%s", (input, date, title) => {
    expect(p(input)).toMatchObject({ date, title });
  });
});

describe("weekdays", () => {
  it("a bare weekday is the soonest one ahead, never today", () => {
    // Today IS Wednesday; "wed" has to mean next week's, or the to-do would be
    // filed on a day the user has already half spent.
    expect(p("review wed").date).toBe("2026-07-22");
    expect(p("review fri").date).toBe("2026-07-17");
    expect(p("复盘 周五").date).toBe("2026-07-17");
    expect(p("休息 周日").date).toBe("2026-07-19");
  });

  it("'next X' means that weekday in the NEXT CALENDAR WEEK", () => {
    // Not "one more week past the soonest one" — that dated 下周二 two weeks out,
    // which is what neither language means.
    expect(p("review next fri").date).toBe("2026-07-24");
    expect(p("复盘 下周五").date).toBe("2026-07-24");
  });

  it("the two spellings agree midweek and diverge on Monday", () => {
    // Wednesday: the soonest Tuesday already IS next week's.
    expect(p("x 周二").date).toBe("2026-07-21");
    expect(p("x 下周二").date).toBe("2026-07-21");
    // Monday: tomorrow vs. eight days out.
    expect(p("x 周二", {}, MON).date).toBe("2026-07-14");
    expect(p("x 下周二", {}, MON).date).toBe("2026-07-21");
    expect(p("x tue", {}, MON).date).toBe("2026-07-14");
    expect(p("x next tue", {}, MON).date).toBe("2026-07-21");
  });
});

describe("durations", () => {
  it.each([
    ["x =15m", 15],
    ["x =2h", 120],
    ["x =45", 45],
    ["写邮件 30分钟", 30],
    ["会议 2小时", 120],
  ])("%s", (input, min) => {
    expect(p(input).min).toBe(min);
  });

  it("leaves out-of-range values in the title instead of sending a 422", () => {
    // The bounds mirror ActionCreate (ge=5, le=480).
    expect(p("x =4m")).toMatchObject({ title: "x =4m", min: undefined });
    expect(p("x =9h")).toMatchObject({ title: "x =9h", min: undefined });
  });

  it("does not turn '=9h' into 9 minutes once it is rejected", () => {
    // Regression: the bare-number rule accepted the "=9" left behind and put an
    // orphaned "h" in the title.
    expect(p("x =9h").title).toBe("x =9h");
  });
});

describe("types", () => {
  it.each([
    ["outreach to L. Chen", "networking"],
    ["内推咨询", "networking"],
    ["apply to HRT", "apply"],
    ["跟进 Stripe", "follow_up"],
    ["follow-up with the recruiter", "follow_up"],
  ])("%s", (input, type) => {
    expect(p(input).type).toBe(type);
  });

  it("keeps the keyword in the title, because it is the verb", () => {
    // Stripping it would leave a title that no longer says what to do.
    expect(p("follow up Stripe").title).toBe("follow up Stripe");
  });
});

describe("does not eat real words", () => {
  // Every one of these used to mangle the title and file the to-do on a day
  // nobody asked for — worse than not parsing, because it is silent.
  it.each([
    "ping Sunday Times about the role",
    "check Monday.com integration",
    "Friday Health Plans screen",
    "reach out re Sun Microsystems",
    "follow up with Wednesday Addams",
    "45分钟内回复 HM",
    "等 30分钟再打",
    "score=42 review",
    "negotiate budget =4500",
  ])("leaves %s intact", (input) => {
    expect(p(input).title).toBe(input);
    expect(p(input).date).toBeUndefined();
  });

  it("still resolves the intent when the keyword really is the intent", () => {
    expect(p("apply to Applied Materials").type).toBe("apply");
    expect(p("reach out re Sun Microsystems").type).toBe("networking");
  });

  it("misses a leading date — the accepted cost of the trailing rule", () => {
    expect(p("friday review Stripe")).toMatchObject({
      title: "friday review Stripe", date: undefined,
    });
  });
});

describe("chip revocation", () => {
  it("drops a rejected match and returns the text to the title", () => {
    expect(p("ping tomorrow =15m", { accept: { date: false } })).toMatchObject({
      title: "ping tomorrow", date: undefined, min: 15,
    });
    expect(p("follow up tomorrow =15m", { accept: { date: false, duration: false, type: false } }))
      .toMatchObject({ title: "follow up tomorrow =15m", date: undefined, min: undefined, type: undefined });
  });
});

describe("no timezone available", () => {
  it("leaves dates in the title rather than guessing a zone", () => {
    // The application detail pane has no workspace settings; resolving against
    // the browser's zone would file the to-do a day off for anyone travelling.
    const r = parseQuickAdd("follow up databricks 下周二 =15m", null, {}, NOW);
    expect(r.title).toBe("follow up databricks 下周二");
    expect(r.date).toBeUndefined();
    expect(r.duration?.minutes).toBe(15);
    expect(r.type?.value).toBe("follow_up");
    expect(dueAtFor(r, null)).toBeUndefined();
  });
});

describe("due_at encoding", () => {
  it("is the UTC instant of local midnight, matching the backend", () => {
    // Same contract as packages/domain/planner/rules.py local_day_start_utc.
    expect(localMidnightUtc("2026-07-16", NY)).toBe("2026-07-16T04:00:00.000Z"); // EDT -4
    expect(localMidnightUtc("2026-01-16", NY)).toBe("2026-01-16T05:00:00.000Z"); // EST -5
    expect(localMidnightUtc("2026-07-16", "Asia/Tokyo")).toBe("2026-07-15T15:00:00.000Z");
  });

  it("handles offsets that are not whole hours", () => {
    expect(localMidnightUtc("2026-07-16", "Asia/Kolkata")).toBe("2026-07-15T18:30:00.000Z");
    expect(localMidnightUtc("2026-07-16", "Australia/Eucla")).toBe("2026-07-15T15:15:00.000Z");
  });

  it("handles both DST switch days", () => {
    expect(localMidnightUtc("2026-03-08", NY)).toBe("2026-03-08T05:00:00.000Z");
    expect(localMidnightUtc("2026-11-01", NY)).toBe("2026-11-01T04:00:00.000Z");
  });

  it("handles a southern-hemisphere switch", () => {
    // Sydney's clocks go forward at 02:00 on 2026-10-04, so midnight that day is
    // still AEST (+10) — 14:00Z the day before, not 13:00Z. Getting this wrong in
    // either direction files the to-do on the neighbouring day.
    expect(localMidnightUtc("2026-10-04", "Australia/Sydney")).toBe("2026-10-03T14:00:00.000Z");
    // The day after the switch is AEDT (+11).
    expect(localMidnightUtc("2026-10-05", "Australia/Sydney")).toBe("2026-10-04T13:00:00.000Z");
  });

  it("threads through dueAtFor", () => {
    expect(dueAtFor(parseQuickAdd("ping tomorrow", NY, {}, NOW), NY))
      .toBe("2026-07-16T04:00:00.000Z");
  });
});

describe("nothing to parse", () => {
  it.each(["update linkedin headline", ""])("%s", (input) => {
    expect(p(input)).toMatchObject({ title: input, date: undefined, min: undefined, type: undefined });
  });

  it("keeps the original text as the title when parsing would empty it", () => {
    // "明天" alone is a date and nothing else; the title falls back to the raw
    // input rather than being submitted empty (the API requires min_length=1).
    expect(p("明天")).toMatchObject({ title: "", date: "2026-07-16" });
  });
});
