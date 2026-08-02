import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

/**
 * A server-measured number on the Plan view comes from usePlannerData, or it
 * goes stale.
 *
 * This has now been the same bug four times, each time in a different number:
 * the week strip kept its dots after a to-do was ticked (V3), the done bar sat
 * at its page-load value all day (V6), the This-week triplet and the pipeline
 * snapshot did the same in the very commit written to end that class (V7-C3),
 * and the funnel was fetched twice — once by the Pipeline zone and once by
 * Today's rail — so confirming an alert in either place left the other showing
 * the old reading, in both directions (V7.5-C3).
 *
 * A component holding its own copy cannot be invalidated by a mutation
 * somewhere else. The store can. So: inside the tracker, these endpoints are
 * called in exactly one place, and any second caller has to be argued for here
 * rather than discovered later by a user reading two contradictory numbers on
 * one screen.
 *
 * Static check — the repo has no jsdom.
 */

const TRACKER = join(__dirname, "..", "app", "[locale]", "tracker");

/** Endpoints that measure something the Plan view renders. getPlannerSettings
 *  is deliberately absent: it is configuration, and SettingsView legitimately
 *  owns its own copy while editing it. */
const MEASURED = ["getFunnel", "getPlannerStats", "getPlannerWeek", "getPlannerDay"];

/** file (relative to the tracker dir) -> endpoints it may call, and why.
 *
 *  Down to one. The exception used to be the Applications sub-view, which never
 *  mounted the Plan store and so fetched the week itself for the server's idea
 *  of "today" (V7-C5). That view is gone, and its Reschedule lives in a panel
 *  that takes the date as a prop instead — which is the shape this guard is
 *  arguing for, so the list shrinking is the point rather than a side effect. */
const ALLOWED: Record<string, string[]> = {
  "usePlannerData.ts": MEASURED, // the store itself
};

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return full.endsWith(".ts") || full.endsWith(".tsx") ? [full] : [];
  });
}

describe("planner sources", () => {
  it("are fetched in one place", () => {
    const offenders: string[] = [];
    for (const file of walk(TRACKER)) {
      if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
      const rel = relative(TRACKER, file);
      const src = readFileSync(file, "utf8");
      const allowed = ALLOWED[rel] ?? [];
      for (const fn of MEASURED) {
        // A call, not an import: `getFunnel(` never matches `getFunnel,`.
        if (!new RegExp(`\\b${fn}\\s*\\(`).test(src)) continue;
        if (allowed.includes(fn)) continue;
        offenders.push(`${rel} calls ${fn}()`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("has no stale entries in the allowlist", () => {
    // An exception nobody uses any more is an exception nobody reconsidered.
    const dead: string[] = [];
    for (const [rel, fns] of Object.entries(ALLOWED)) {
      const src = readFileSync(join(TRACKER, rel), "utf8");
      for (const fn of fns) {
        if (!new RegExp(`\\b${fn}\\s*\\(`).test(src)) dead.push(`${rel} no longer calls ${fn}()`);
      }
    }
    expect(dead).toEqual([]);
  });
});
