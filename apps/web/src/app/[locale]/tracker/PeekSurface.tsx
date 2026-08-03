"use client";

import { useEffect, useRef, useState } from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { clampAnchor } from "./peekAnchor";

/** Rows that can open the panel carry this, and it is how the panel finds the
 *  one that opened it. An attribute rather than a ref passed up through props:
 *  the two openers live in different components (the sidebar's rows and Today's
 *  to-do rows) and a third would otherwise mean a third wire. It also works for
 *  a row opened from the keyboard, which never produces a pointer position. */
export const PEEK_ANCHOR_ATTR = "data-peek-anchor";

/** Wide enough for the editing form; the plan column keeps the rest. */
const PANEL_W = 400;
/** Below this the sidebar stacks above the plan (see PlanView's grid), so
 *  "beside the row" has no meaning and the panel goes back to the edge. */
const ANCHORED_FROM = 1100;

/**
 * Where the peek panel is drawn.
 *
 * Two presentations, one set of children — the panel's contents never learn
 * which one they are in, or the two would drift the first time either is
 * touched.
 *
 * WIDE: a card inside the plan column, level with the row that opened it, with
 * no backdrop. Deliberately NOT a modal. A peek is a glance at something while
 * you keep working, so the page stays scrollable and clickable behind it, and
 * clicking a different row swaps the subject rather than closing and reopening.
 * The price is that focus management is ours: the dialog primitive is what
 * normally traps and restores focus, and none of it happens here for free.
 *
 * NARROW: the sheet it has always been. Below the breakpoint the sidebar is
 * above the plan rather than beside it, so there is no "right of the row" to
 * anchor to, and an edge sheet is the correct shape rather than a fallback.
 */
export function PeekSurface({
  open,
  anchorId,
  onClose,
  onDismiss,
  label,
  children,
}: {
  open: boolean;
  /** The row to sit level with — an action id or an application id, matching
   *  whatever the opener stamped on itself. Null anchors to the top. */
  anchorId: string | null;
  onClose: () => void;
  /** Offered a chance to swallow a dismissal before it closes the panel.
   *  Return true to keep it open. The panel can be showing a form the user is
   *  half way through, and only its contents know that — the surface knows how
   *  the dismissal was asked for, which is the other half of the decision. */
  onDismiss?: (reason: "escape" | "outside") => boolean;
  label: string;
  children: React.ReactNode;
}) {
  const [anchored, setAnchored] = useState(false);
  const [top, setTop] = useState(8);
  const cardRef = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  // Which presentation. Read from a media query rather than a resize handler so
  // it only re-renders when the answer actually changes, and evaluated in an
  // effect because the server has no window and must not guess.
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${ANCHORED_FROM}px)`);
    const sync = () => setAnchored(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  // Position, recomputed whenever the subject or the geometry changes. The
  // measurement is (row - host) in viewport coordinates, which cancels the
  // scroll offset: the result is where the row sits INSIDE the host, so the
  // card scrolls with the content and stays level with its row without a
  // scroll listener.
  useEffect(() => {
    if (!open || !anchored) return;
    const place = () => {
      const host = cardRef.current?.offsetParent as HTMLElement | null;
      if (!host) return;
      const row = anchorId
        ? document.querySelector<HTMLElement>(`[${PEEK_ANCHOR_ATTR}="${CSS.escape(anchorId)}"]`)
        : null;
      const anchorY = row
        ? row.getBoundingClientRect().top - host.getBoundingClientRect().top
        : 0;
      setTop(
        clampAnchor({
          anchorY,
          panelH: cardRef.current?.offsetHeight ?? 0,
          hostH: host.offsetHeight,
        }),
      );
    };
    place();
    // The card's own height settles a frame later (the application loads, the
    // timeline fills in), and a stale height clamps against the wrong number.
    const ro = new ResizeObserver(place);
    if (cardRef.current) ro.observe(cardRef.current);
    window.addEventListener("resize", place);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", place);
    };
  }, [open, anchored, anchorId]);

  // Focus: into the card on open, back to the row that opened it on close.
  // The sheet gets this from its dialog primitive; the card has to be told.
  useEffect(() => {
    if (!anchored) return;
    if (open) {
      restoreTo.current = document.activeElement as HTMLElement | null;
      cardRef.current?.focus();
      return;
    }
    // Only reclaim focus if it is still loose in the body. Returning it after
    // the user has clicked into something else would yank them backwards.
    const target = restoreTo.current;
    restoreTo.current = null;
    if (target?.isConnected && document.activeElement === document.body) target.focus();
  }, [open, anchored]);

  // Escape, and a click outside. Both skip anchor rows: clicking another row
  // while the panel is open is a change of subject, and closing first would
  // make it blink. `pointerdown` rather than `click` so a press that starts
  // outside and drags in (selecting text) does not count as an outside click.
  useEffect(() => {
    if (!open || !anchored) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (onDismiss?.("escape")) return;
      onClose();
    };
    const onDown = (e: PointerEvent) => {
      const el = e.target as HTMLElement | null;
      if (!el || cardRef.current?.contains(el) || el.closest(`[${PEEK_ANCHOR_ATTR}]`)) return;
      if (onDismiss?.("outside")) return;
      onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [open, anchored, onClose, onDismiss]);

  if (!anchored) {
    return (
      <Sheet
        open={open}
        // Base UI reports a dismissal without saying how it was asked for, so
        // this reads as the cautious one: on a narrow screen a half-finished
        // form is kept rather than discarded, and the panel is left by its own
        // Back or close button.
        onOpenChange={(next) => { if (next) return; if (onDismiss?.("outside")) return; onClose(); }}
      >
        <SheetContent className="max-w-[430px] flex flex-col gap-0 p-0">
          {/* The accessible name belongs to whichever surface is rendered, so it
              lives here rather than in the contents. SheetTitle is a Base UI
              Dialog.Title and reads the dialog context — rendered inside the
              anchored card, which has no Dialog above it, it does not degrade,
              it throws and takes the whole page with it. */}
          <SheetTitle className="sr-only">{label}</SheetTitle>
          {children}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <div
      ref={cardRef}
      role="dialog"
      aria-label={label}
      tabIndex={-1}
      hidden={!open}
      className="absolute left-0 z-30 flex flex-col rounded-xl border shadow-xl outline-none"
      style={{
        top,
        width: PANEL_W,
        maxHeight: "min(78vh, 720px)",
        // --card, not --surface: the latter does not exist in this stylesheet,
        // and an undefined custom property with no fallback resolves to nothing
        // rather than erroring — the card rendered fully transparent, with the
        // plan legible straight through it. The sheet this replaces used a
        // literal bg-white, which is why it never showed the gap.
        background: "var(--card)",
        borderColor: "var(--border)",
      }}
    >
      {children}
    </div>
  );
}
