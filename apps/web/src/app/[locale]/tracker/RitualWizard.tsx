"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import type { ActionRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { CapacityMeter, estOf, fmtMinutes } from "./capacity";

/** What the user decided about one piece of yesterday's leftover work. */
export type CarryChoice = "today" | "tomorrow" | "drop";

export interface RitualResult {
  /** Ids kept for today — the commitment that gets filed. */
  keptIds: string[];
  /** Ids to push to tomorrow: everything unticked, plus carried work sent on. */
  deferIds: string[];
  /** Ids to dismiss — work the user decided not to do at all. */
  dropIds: string[];
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
 */
export function RitualWizard({
  open,
  onOpenChange,
  actions,
  cap,
  overdue,
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
  onApply: (result: RitualResult) => void;
  applying: boolean;
}) {
  const t = useTranslations("tracker");
  const [step, setStep] = useState(1);
  const [carry, setCarry] = useState<Record<string, CarryChoice>>({});
  const [kept, setKept] = useState<Set<string> | null>(null);

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
  const committed = keptList.reduce((sum, a) => sum + estOf(a), 0);
  const pct = cap > 0 ? Math.round((committed / cap) * 100) : 0;

  function reset() {
    setStep(1);
    setCarry({});
    setKept(null);
  }

  function close(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

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
    });
  }

  const steps = [1, 2, 3];

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-lg">
        <DialogTitle className="text-base font-semibold">
          {t(step === 1 ? "ritualStep1Title" : step === 2 ? "ritualStep2Title" : "ritualStep3Title")}
        </DialogTitle>
        <DialogDescription className="text-xs" style={{ color: "var(--ink-muted)" }}>
          {t(step === 1 ? "ritualStep1Sub" : step === 2 ? "ritualStep2Sub" : "ritualStep3Sub")}
        </DialogDescription>

        {/* step dots */}
        <div className="flex gap-1.5 mt-2 mb-3" aria-hidden>
          {steps.map((s) => (
            <span
              key={s}
              className="h-1 flex-1 rounded-full"
              style={{ background: s <= step ? "var(--primary)" : "var(--muted)" }}
            />
          ))}
        </div>

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
              {cap > 0 && (
                <div className="rounded-lg border p-3 mb-2" style={{ borderColor: "var(--border)" }}>
                  <CapacityMeter used={committed} cap={cap} />
                </div>
              )}
              {candidates.length === 0 ? (
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
            </>
          )}

          {step === 3 && (
            <div className="rounded-lg border p-4" style={{ borderColor: "var(--border)" }}>
              <div className="text-lg font-semibold tabular-nums" style={{ color: "var(--ink-primary)" }}>
                {t("ritualConfirmCount", { n: keptList.length, minutes: fmtMinutes(committed) })}
              </div>
              {cap > 0 && (
                <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
                  {t(pct <= 85 ? "ritualConfirmRoomy" : "ritualConfirmTight", { pct })}
                </p>
              )}
              <p className="text-2xs mt-3" style={{ color: "var(--ink-faint)" }}>
                {t("ritualConfirmMoved", {
                  n: candidates.length - keptList.length,
                  dropped: Object.values(carry).filter((c) => c === "drop").length,
                })}
              </p>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 mt-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => (step === 1 ? close(false) : setStep(step - 1))}
          >
            {t(step === 1 ? "cancel" : "ritualBack")}
          </Button>
          <span className="flex-1" />
          {step < 3 ? (
            <Button size="sm" onClick={() => setStep(step + 1)}>{t("ritualNext")}</Button>
          ) : (
            <Button size="sm" onClick={apply} loading={applying}>{t("ritualCommit")}</Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
