"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { ActionRead, ApplicationRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { DropAcknowledgement, dropGateBlocks } from "./DropAcknowledgement";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { CapacityMeter, EST_FALLBACK, estOf, fmtMinutes } from "./capacity";
import { ritualSteps } from "./ritual";
import { isFresh } from "./queueRank";

/** What the user decided about one piece of yesterday's leftover work. */
export type CarryChoice = "today" | "tomorrow" | "drop";

export interface RitualResult {
  /** Ids kept for today — the commitment that gets filed. */
  keptIds: string[];
  /** Ids to push to tomorrow: everything unticked, plus carried work sent on. */
  deferIds: string[];
  /** Ids to dismiss — work the user decided not to do at all. */
  dropIds: string[];
  /** APPLICATION ids the user pulled in from the queue. Application ids, never
   *  action ids: nothing exists for these yet, and the wizard does not create
   *  it. A synthesised id mixed into keptIds would be filed as a commitment
   *  worth zero minutes and never noticed (see mergeCommitIds), and one sent to
   *  PATCH /actions/{id} would 404 the whole ritual. The caller creates, and
   *  only real ids come back from that. */
  queueApplicationIds: string[];
}

/** Morning planning, in three steps.
 *
 *  The order is the point, and it is not the order a to-do list suggests.
 *  Yesterday's leftovers come FIRST, before anything about today, because an
 *  unfinished item that silently rolls over is the thing that turns a plan into
 *  a debt: you never decided to carry it, it just arrived. Step one forces the
 *  decision — do it, move it, or drop it — so what reaches step two is a list
 *  someone chose.
 *
 *  Step two is where the capacity reading belongs: while you are ticking boxes,
 *  not after you have committed. Step three states the total back before it is
 *  filed, because the number that gets stored as "what I agreed to" should be
 *  one the user has actually read.
 *
 *  On a morning with no leftovers, step one is skipped rather than shown empty.
 *  The decision it forces is the whole reason it goes first, and when there is
 *  nothing to decide it degrades into a screen whose only content is the word
 *  "Nothing" and a Next button — which is how a daily ritual becomes a thing
 *  people click through instead of a thing they do. Nothing is lost by
 *  skipping: with no leftovers there is nothing for step one to write.
 */
export function RitualWizard({
  open,
  onOpenChange,
  actions,
  cap,
  overdue,
  startAtStep,
  queue,
  freshDays,
  onApply,
  applying,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Candidates for today — what the Today list already counts against the cap. */
  actions: ActionRead[];
  cap: number;
  /** Work that came due before today and is still pending. */
  overdue: ActionRead[];
  /** Where to open: 1 when there are leftovers to decide (or we cannot yet tell
   *  whether there are), 2 when there are demonstrably none. See ritual.ts. */
  startAtStep: 1 | 2;
  /** Queued applications that can be pulled into today, already ranked and
   *  already deduplicated against existing apply to-dos by the caller. */
  queue: ApplicationRead[];
  /** How recently a posting counts as fresh — for the badge, matching the
   *  sidebar's. */
  freshDays: number;
  onApply: (result: RitualResult) => void;
  applying: boolean;
}) {
  const t = useTranslations("tracker");
  // Widened deliberately: seeding from a `1 | 2` prop narrows the state to the
  // steps it can START on, which makes `step === 3` a comparison tsc reports as
  // impossible and `setStep(step + 1)` a type error — the confirm step exists,
  // it just is not somewhere the wizard opens.
  const [step, setStep] = useState<number>(startAtStep);
  const [carry, setCarry] = useState<Record<string, CarryChoice>>({});
  const [kept, setKept] = useState<Set<string> | null>(null);
  const [ackDrop, setAckDrop] = useState(false);
  /** Queued APPLICATIONS ticked to become today's work. Off by default: pulling
   *  new work in is a thing to choose, not a thing to notice and undo. */
  const [pulled, setPulled] = useState<Set<string>>(new Set());

  // Default ticks: dated work is on, undated ("anytime") is off. Undated work
  // is what the day absorbs when there is room, so it should be an opt-in
  // rather than something the user has to notice and remove.
  const defaultKept = useMemo(
    () => new Set(actions.filter((a) => a.due_at).map((a) => a.id)),
    [actions],
  );
  const ticked = kept ?? defaultKept;

  // A carried item the user dropped or moved is no longer a candidate for today.
  const carriedAway = new Set(
    Object.entries(carry).filter(([, c]) => c !== "today").map(([id]) => id),
  );
  const candidates = actions.filter((a) => !carriedAway.has(a.id));
  const keptList = candidates.filter((a) => ticked.has(a.id));
  // The to-dos that do not exist yet count too. They are what the user is
  // agreeing to as much as the ticked rows are, and the capacity bar that omits
  // them tells someone a full day is a light one — the exact reading the meter
  // exists to prevent. The minute figure is EST_FALLBACK's, which is the number
  // the server will reach for the same row: create sends no est_minutes, so
  // effective_est_minutes() fills it from the table this one is asserted equal
  // to. One number, two tables that a test keeps in step; not a third literal.
  const pulledMinutes = pulled.size * EST_FALLBACK.apply;
  const committed = keptList.reduce((sum, a) => sum + estOf(a), 0) + pulledMinutes;
  const pct = cap > 0 ? Math.round((committed / cap) * 100) : 0;
  const dropCount = Object.values(carry).filter((c) => c === "drop").length;

  function reset() {
    setStep(startAtStep);
    setCarry({});
    setAckDrop(false);
    setKept(null);
    setPulled(new Set());
  }

  function close(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  // The starting step is applied when the dialog OPENS, not when this component
  // mounts. `open` is a prop and this wizard is rendered unconditionally, so it
  // mounts with the Plan view — before actions, week or settings have arrived,
  // when the plate always looks empty. useState(startAtStep) would therefore
  // freeze it on step 2 for the whole session, and no later data could move it.
  // Only on the closed→open edge: recomputing while open would yank someone
  // mid-answer if a background refresh changed the plate under them.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) setStep(startAtStep);
    wasOpen.current = open;
  }, [open, startAtStep]);

  function apply() {
    const dropIds = Object.entries(carry).filter(([, c]) => c === "drop").map(([id]) => id);
    const carriedTomorrow = Object.entries(carry)
      .filter(([, c]) => c === "tomorrow")
      .map(([id]) => id);
    // Everything left on the table goes to tomorrow. Not "nothing happens to
    // it": an unticked to-do that stays due today would reappear in the very
    // list the ritual just cleared, which is how a plan stops meaning anything.
    const untickedToday = candidates.filter((a) => !ticked.has(a.id)).map((a) => a.id);
    onApply({
      keptIds: keptList.map((a) => a.id),
      deferIds: [...new Set([...carriedTomorrow, ...untickedToday])],
      dropIds,
      // Only what is still on offer: a row the caller has since deduplicated
      // away must not be pulled twice because it was ticked before a refresh.
      queueApplicationIds: queue.filter((a) => pulled.has(a.id)).map((a) => a.id),
    });
  }

  const steps = ritualSteps(startAtStep);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-lg">
        <DialogTitle className="text-base font-semibold">
          {t(step === 1 ? "ritualStep1Title" : step === 2 ? "ritualStep2Title" : "ritualStep3Title")}
        </DialogTitle>
        <DialogDescription className="text-xs" style={{ color: "var(--ink-muted)" }}>
          {t(step === 1 ? "ritualStep1Sub" : step === 2 ? "ritualStep2Sub" : "ritualStep3Sub")}
        </DialogDescription>

        {/* Step dots, drawn from the steps that exist rather than from a
            literal [1,2,3]: three dots above a two-step flow promise a screen
            that never comes, and the first would sit unfillable. The titles
            used to carry "1/3 · " and so on, which is the same claim in a place
            the component cannot keep honest — the position is stated once, here,
            computed from the same array that draws it. */}
        <div className="flex gap-1.5 mt-2 mb-3" aria-hidden>
          {steps.map((s) => (
            <span
              key={s}
              className="h-1 flex-1 rounded-full"
              style={{ background: s <= step ? "var(--primary)" : "var(--muted)" }}
            />
          ))}
        </div>
        <span className="sr-only" role="status" aria-live="polite">
          {t("ritualStepProgress", { n: steps.indexOf(step) + 1, total: steps.length })}
        </span>

        <div className="max-h-[46vh] overflow-y-auto -mx-1 px-1 space-y-2">
          {step === 1 && (
            overdue.length === 0 ? (
              <p className="text-sm py-4 text-center" style={{ color: "var(--ink-muted)" }}>
                {t("ritualNoCarry")}
              </p>
            ) : (
              overdue.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center gap-3 rounded-lg border px-3 py-2"
                  style={{ borderColor: "var(--border)" }}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate" style={{ color: "var(--ink-primary)" }}>{a.title}</div>
                    <div className="text-2xs" style={{ color: "var(--ink-faint)" }}>
                      {t("estMinutes", { minutes: estOf(a) })}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    {(["today", "tomorrow", "drop"] as CarryChoice[]).map((choice) => {
                      const on = (carry[a.id] ?? "today") === choice;
                      return (
                        <Button
                          key={choice}
                          size="sm"
                          variant={on ? "outline" : "ghost"}
                          onClick={() => setCarry((prev) => ({ ...prev, [a.id]: choice }))}
                        >
                          {t(
                            choice === "today"
                              ? "ritualCarryToday"
                              : choice === "tomorrow"
                                ? "ritualCarryTomorrow"
                                : "ritualCarryDrop",
                          )}
                        </Button>
                      );
                    })}
                  </div>
                </div>
              ))
            )
          )}

          {step === 2 && (
            <>
              {/* Why this morning has two steps and not three. A flow that
                  silently drops a step reads as a flow that lost one. */}
              {startAtStep === 2 && (
                <p className="text-2xs mb-2" style={{ color: "var(--ink-faint)" }}>
                  {t("ritualStepSkipped")}
                </p>
              )}
              {cap > 0 && (
                <div className="rounded-lg border p-3 mb-2" style={{ borderColor: "var(--border)" }}>
                  <CapacityMeter used={committed} cap={cap} />
                </div>
              )}
              {candidates.length === 0 && queue.length === 0 ? (
                <p className="text-sm py-4 text-center" style={{ color: "var(--ink-muted)" }}>
                  {t("ritualNothingToPick")}
                </p>
              ) : (
                candidates.map((a) => (
                  <label
                    key={a.id}
                    className="flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <input
                      type="checkbox"
                      checked={ticked.has(a.id)}
                      onChange={(e) => {
                        const next = new Set(ticked);
                        if (e.target.checked) next.add(a.id);
                        else next.delete(a.id);
                        setKept(next);
                      }}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm truncate" style={{ color: "var(--ink-primary)" }}>{a.title}</div>
                      <div className="text-2xs" style={{ color: "var(--ink-faint)" }}>
                        {t("estMinutes", { minutes: estOf(a) })}
                      </div>
                    </div>
                  </label>
                ))
              )}

              {/* Building the plate, not just trimming it. Without this the
                  ritual can only ever subtract from a list something else
                  filled, which on a clear morning means it has nothing to do.
                  Ticking one does not create anything here — the wizard reports
                  which APPLICATIONS were chosen and the caller writes the
                  to-dos, because creating from inside a step the user can still
                  go Back from would leave rows behind on every cancel. */}
              {queue.length > 0 && (
                <div className="mt-4">
                  <p className="text-2xs mb-1.5" style={{ color: "var(--ink-faint)" }}>
                    {t("ritualQueueHead")}
                  </p>
                  {queue.map((a) => (
                    <label
                      key={a.id}
                      className="flex items-center gap-3 rounded-lg border px-3 py-2 mb-2 cursor-pointer"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <input
                        type="checkbox"
                        checked={pulled.has(a.id)}
                        onChange={(e) => {
                          const next = new Set(pulled);
                          if (e.target.checked) next.add(a.id);
                          else next.delete(a.id);
                          setPulled(next);
                        }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm truncate" style={{ color: "var(--ink-primary)" }}>
                          {t("ritualQueueRow", {
                            company: a.job?.company ?? "—",
                            role: a.job?.title ?? "",
                          })}
                        </div>
                        <div className="text-2xs truncate" style={{ color: "var(--ink-faint)" }}>
                          {[
                            typeof a.fit_score === "number" ? t("ritualQueueFit", { fit: a.fit_score }) : null,
                            (a.excitement ?? 0) > 0 ? "★".repeat(a.excitement ?? 0) : null,
                            isFresh(a.job?.posted_at, freshDays) ? t("ritualQueueFresh") : null,
                          ].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                      <span className="shrink-0 text-2xs" style={{ color: "var(--ink-muted)" }}>
                        {t("estMinutes", { minutes: EST_FALLBACK.apply })}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </>
          )}

          {step === 3 && (
            <div className="rounded-lg border p-4" style={{ borderColor: "var(--border)" }}>
              <div className="text-lg font-semibold tabular-nums" style={{ color: "var(--ink-primary)" }}>
                {/* Both halves of the same commitment. `committed` already
                    includes the pulled work, so counting only keptList here
                    would print a count and a duration that describe different
                    sets — "3 to-dos · 4h" for five. */}
                {t("ritualConfirmCount", {
                  n: keptList.length + pulled.size,
                  minutes: fmtMinutes(committed),
                })}
              </div>
              {cap > 0 && (
                <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
                  {t(pct <= 85 ? "ritualConfirmRoomy" : "ritualConfirmTight", { pct })}
                </p>
              )}
              <p className="text-2xs mt-3" style={{ color: "var(--ink-faint)" }}>
                {/* Everything the Commit will move, including the leftovers sent
                    on in step 1 — they are not in `candidates`, so counting only
                    unticked rows understated it and the confirmation described a
                    smaller action than the button performs. */}
                {t("ritualConfirmMoved", {
                  n:
                    candidates.length -
                    keptList.length +
                    Object.values(carry).filter((c) => c === "tomorrow").length,
                  dropped: dropCount,
                })}
              </p>
              <DropAcknowledgement
                count={dropCount}
                checked={ackDrop}
                onChange={setAckDrop}
                label={t("dropAcknowledge", { n: dropCount })}
              />
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 mt-4">
          {/* Back leaves the wizard at the FIRST REACHABLE step, not at step 1.
              Keyed to the literal it would walk backwards into a step this
              morning skipped — one that renders "Nothing carried over" directly
              after a chip said it was skipped for having nothing in it. */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => (step === startAtStep ? close(false) : setStep(step - 1))}
          >
            {t(step === startAtStep ? "ritualCancel" : "ritualBack")}
          </Button>
          <span className="flex-1" />
          {step < 3 ? (
            <Button size="sm" onClick={() => setStep(step + 1)}>{t("ritualNext")}</Button>
          ) : (
            <Button
              size="sm"
              onClick={apply}
              loading={applying}
              disabled={dropGateBlocks(dropCount, ackDrop)}
            >
              {t("ritualCommit")}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
