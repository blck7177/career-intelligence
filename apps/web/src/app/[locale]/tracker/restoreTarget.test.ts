import { describe, it, expect } from "vitest";
import { restoreTargetOf } from "./status";

/** Reopening a mis-closed application has to land somewhere. These pin the
 *  "somewhere": the status it actually held before the close, never a guess
 *  dressed up as a record. */

const ev = (from: string, to: string, created_at: string) => ({
  event_type: "status_changed",
  payload_json: { from, to, forced: false },
  created_at,
});

describe("restoreTargetOf", () => {
  it("restores the status the application held when it was closed", () => {
    const app = {
      status: "ghosted",
      events: [
        ev("planned", "applied", "2026-07-01T10:00:00Z"),
        ev("applied", "interviewing", "2026-07-10T10:00:00Z"),
        ev("interviewing", "ghosted", "2026-07-25T10:00:00Z"),
      ],
    };
    expect(restoreTargetOf(app)).toBe("interviewing");
  });

  it("does not depend on the order the events arrive in", () => {
    // Same three moves, shuffled. A positional read (last match wins) returns
    // "applied" here; the max(created_at) read returns the real answer. The
    // endpoint sorts ascending today — this is what stops that from being
    // load-bearing.
    const app = {
      status: "ghosted",
      events: [
        ev("interviewing", "ghosted", "2026-07-25T10:00:00Z"),
        ev("planned", "applied", "2026-07-01T10:00:00Z"),
        ev("applied", "ghosted", "2026-07-05T10:00:00Z"),
      ],
    };
    expect(restoreTargetOf(app)).toBe("interviewing");
  });

  it("uses the most recent close when the application was reopened and closed again", () => {
    const app = {
      status: "rejected",
      events: [
        ev("applied", "rejected", "2026-07-02T10:00:00Z"),
        ev("rejected", "applied", "2026-07-03T10:00:00Z"),
        ev("applied", "offer", "2026-07-20T10:00:00Z"),
        ev("offer", "rejected", "2026-07-28T10:00:00Z"),
      ],
    };
    expect(restoreTargetOf(app)).toBe("offer");
  });

  it("ignores moves that landed on a different closed status", () => {
    const app = {
      status: "withdrawn",
      events: [
        ev("applied", "ghosted", "2026-07-20T10:00:00Z"),
        ev("ghosted", "withdrawn", "2026-07-21T10:00:00Z"), // from is closed, not a live stage
      ],
    };
    // Nothing usable was recorded, so it says so by falling back rather than
    // offering to "restore" the application to ghosted.
    expect(restoreTargetOf(app)).toBe("applied");
  });

  it("falls back to applied when there is no status history at all", () => {
    expect(restoreTargetOf({ status: "ghosted", events: [] })).toBe("applied");
    expect(restoreTargetOf({ status: "ghosted" })).toBe("applied");
  });

  it("ignores non-status events and unparseable timestamps", () => {
    const app = {
      status: "ghosted",
      events: [
        { event_type: "note", payload_json: null, created_at: "2026-07-26T10:00:00Z" },
        ev("in_review", "ghosted", "not-a-date"),
        ev("applied", "ghosted", "2026-07-25T10:00:00Z"),
      ],
    };
    expect(restoreTargetOf(app)).toBe("applied");
  });
});
