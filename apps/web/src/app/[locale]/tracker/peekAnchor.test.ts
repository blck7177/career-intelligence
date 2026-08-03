import { describe, expect, it } from "vitest";
import { clampAnchor } from "./peekAnchor";

// A tall host with room to spare, so the interesting cases are the edges.
const HOST = { panelH: 400, hostH: 1200 };

describe("clampAnchor", () => {
  it("puts the panel level with its row when there is room", () => {
    expect(clampAnchor({ anchorY: 300, ...HOST })).toBe(300);
  });

  it("keeps a row at the very top off the host's edge", () => {
    // anchorY 0 is the first row of the sidebar's first group.
    expect(clampAnchor({ anchorY: 0, ...HOST })).toBe(8);
    expect(clampAnchor({ anchorY: -40, ...HOST })).toBe(8);
  });

  it("slides up rather than overflowing when the row is near the bottom", () => {
    // The last row of a long queue: 1150 + 400 would run 350px past the host.
    expect(clampAnchor({ anchorY: 1150, ...HOST })).toBe(1200 - 400 - 8);
  });

  it("never returns a top that puts any of the panel past the host", () => {
    for (const anchorY of [-100, 0, 1, 250, 799, 800, 801, 1199, 5000]) {
      const top = clampAnchor({ anchorY, ...HOST });
      expect(top).toBeGreaterThanOrEqual(8);
      expect(top + HOST.panelH).toBeLessThanOrEqual(HOST.hostH - 8);
    }
  });

  it("pins to the top when the panel is taller than the host", () => {
    // A short plan — one zone, no week strip — with a full-height panel. The
    // arithmetic for "lowest" goes negative here, and returning it would scroll
    // the panel's own header out of reach.
    expect(clampAnchor({ anchorY: 500, panelH: 900, hostH: 600 })).toBe(8);
    expect(clampAnchor({ anchorY: 0, panelH: 900, hostH: 600 })).toBe(8);
  });

  it("is monotonic — a lower row never yields a higher panel", () => {
    // What makes the position feel attached to the row rather than arbitrary.
    let prev = -Infinity;
    for (let y = -50; y <= 1300; y += 25) {
      const top = clampAnchor({ anchorY: y, ...HOST });
      expect(top).toBeGreaterThanOrEqual(prev);
      prev = top;
    }
  });

  it("honours a custom pad on both edges", () => {
    expect(clampAnchor({ anchorY: 0, ...HOST, pad: 24 })).toBe(24);
    expect(clampAnchor({ anchorY: 9999, ...HOST, pad: 24 })).toBe(1200 - 400 - 24);
  });
});
