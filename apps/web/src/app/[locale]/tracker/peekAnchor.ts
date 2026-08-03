// Where the peek panel sits when it is anchored to the row that opened it.
//
// The panel used to slide in from the right edge of the viewport. On a 1500px
// plan view that put it a full screen away from the sidebar rows that open it —
// and the right edge is where the agent chat is going, so it was borrowed
// space. Anchored, it appears beside its own row: the eye barely moves, and the
// column order stays sidebar → detail → plan → chat.
//
// Pure so the clamping can be tested. Every value is in the HOST's coordinate
// space (the positioned element the panel is absolutely placed in), never the
// viewport's — the host scrolls with the content, so a top computed once stays
// correct through scrolling with no listener.

export interface AnchorBox {
  /** Row top, measured as (rowRect.top - hostRect.top). Both are viewport
   *  coordinates, so the scroll offset cancels and the result is the row's
   *  position inside the host. */
  anchorY: number;
  /** Rendered height of the panel. */
  panelH: number;
  /** Scrollable height of the host column. */
  hostH: number;
  /** Breathing room kept at the host's top and bottom edges. */
  pad?: number;
}

/**
 * The panel's `top`, clamped so it never hangs off either end of the host.
 *
 * Clamped, not flipped. A flip (open upward when the row is low) moves the
 * panel to the opposite side of the pointer, which is the one thing anchoring
 * was for — and it makes the position depend on where you happened to click,
 * so the same row can open in two places on two different scroll positions.
 * Sliding it up until it fits keeps it beside the row in every case where it
 * fits, and directly below the last possible position when it does not.
 *
 * A panel taller than its host is not an error — it is what a short plan (one
 * zone, no strip) produces — and it needs no branch of its own: `lowest` goes
 * negative, Math.min takes it, and the outer Math.max pins the result to `pad`.
 * An explicit early return for that case was written here first and deleted
 * again: every mutation of it left the tests green, because it could not change
 * an answer. The case is still asserted below.
 */
export function clampAnchor({ anchorY, panelH, hostH, pad = 8 }: AnchorBox): number {
  const lowest = hostH - panelH - pad;
  return Math.max(pad, Math.min(anchorY, lowest));
}
