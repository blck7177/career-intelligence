"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { ActionRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { DropAcknowledgement, dropGateBlocks } from "./DropAcknowledgement";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { estOf, fmtMinutes } from "./capacity";

export type LeftoverChoice = "tomorrow" | "next_week" | "drop";

export interface ShutdownResult {
  /** Ids to push to tomorrow. */
  tomorrowIds: string[];
  /** Ids to push a week out. */
  nextWeekIds: string[];
  /** Ids to dismiss. */
  dropIds: string[];
  reflection: string | null;
}

/** Evening shutdown.
 *
 *  The point is not bookkeeping — it is that an open day has a cost. Work you
 *  did not finish keeps running in the background as a vague sense of being
 *  behind, and the only thing that stops it is deciding, explicitly, where each
 *  piece goes. So every leftover gets a destination before the day can close;
 *  nothing is left in the ambiguous state that generates the feeling.
 *
 *  The reflection is optional and stays one line. It becomes material for the
 *  weekly review, which quotes rather than re-narrates it. */
export function ShutdownWizard({
  open,
  onOpenChange,
  leftovers,
  doneCount,
  doneEst,
  today,
  yesterday,
  closingDate,
  onClosingDateChange,
  onApply,
  applying,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Still-open to-dos that counted toward today. */
  leftovers: ActionRead[];
  doneCount: number;
  doneEst: number;
  /** The day the server labelled today, and the one before it. */
  today: string | null;
  yesterday: string | null;
  /** Which day this close will file against; null means today. */
  closingDate: string | null;
  onClosingDateChange: (date: string | null) => void;
  onApply: (result: ShutdownResult) => void;
  applying: boolean;
}) {
  const t = useTranslations("tracker");
  const [choices, setChoices] = useState<Record<string, LeftoverChoice>>({});
  const [ackDrop, setAckDrop] = useState(false);
  const [reflection, setReflection] = useState("");

  function close(next: boolean) {
    if (!next) {
      setChoices({});
      setReflection("");
      // The gate has to re-arm. A stale tick would pre-acknowledge the NEXT
      // set of drops, which is a gate that only ever stops the first one.
      setAckDrop(false);
    }
    onOpenChange(next);
  }

  const dropCount = leftovers.filter((a) => (choices[a.id] ?? "tomorrow") === "drop").length;

  function apply() {
    const pick = (want: LeftoverChoice) =>
      leftovers
        .filter((a) => (choices[a.id] ?? "tomorrow") === want)
        .map((a) => a.id);
    onApply({
      tomorrowIds: pick("tomorrow"),
      nextWeekIds: pick("next_week"),
      dropIds: pick("drop"),
      reflection: reflection.trim() || null,
    });
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-lg">
        <DialogTitle className="text-base font-semibold">{t("shutdownTitle")}</DialogTitle>
        <DialogDescription className="text-xs" style={{ color: "var(--ink-muted)" }}>
          {t("shutdownSub")}
        </DialogDescription>

        {/* Which day is being ended. Named rather than assumed, because a job
            search runs past midnight and at 00:30 the server's "today" is a day
            that has not started — closing it would stamp the new day finished
            before it began. The choice is offered, never inferred: guessing
            from the clock would move someone's records without asking. */}
        {today && (
          <div className="flex flex-wrap items-center gap-2 mt-2 text-2xs">
            <span style={{ color: "var(--ink-faint)" }}>
              {t("shutdownClosingDay", { date: closingDate ?? today })}
            </span>
            {yesterday && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onClosingDateChange(closingDate === yesterday ? null : yesterday)}
              >
                {t(closingDate === yesterday ? "shutdownCloseToday" : "shutdownCloseYesterday")}
              </Button>
            )}
          </div>
        )}

        <div className="max-h-[46vh] overflow-y-auto -mx-1 px-1 mt-3 space-y-2">
          <div className="rounded-lg border p-4" style={{ borderColor: "var(--border)" }}>
            <div className="text-lg font-semibold tabular-nums" style={{ color: "var(--ink-primary)" }}>
              {t("shutdownDone", { n: doneCount, minutes: fmtMinutes(doneEst) })}
            </div>
          </div>

          {leftovers.length === 0 ? (
            <p className="text-sm py-3 text-center font-semibold" style={{ color: "var(--match-good-fg)" }}>
              {t("shutdownAllClear")}
            </p>
          ) : (
            leftovers.map((a) => (
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
                  {(["tomorrow", "next_week", "drop"] as LeftoverChoice[]).map((choice) => {
                    const on = (choices[a.id] ?? "tomorrow") === choice;
                    return (
                      <Button
                        key={choice}
                        size="sm"
                        variant={on ? "outline" : "ghost"}
                        onClick={() => setChoices((prev) => ({ ...prev, [a.id]: choice }))}
                      >
                        {t(
                          choice === "tomorrow"
                            ? "ritualCarryTomorrow"
                            : choice === "next_week"
                              ? "shutdownNextWeek"
                              : "ritualCarryDrop",
                        )}
                      </Button>
                    );
                  })}
                </div>
              </div>
            ))
          )}

          <div className="pt-2">
            <div className="text-2xs uppercase tracking-wide mb-1" style={{ color: "var(--ink-faint)" }}>
              {t("shutdownReflectionLabel")}
            </div>
            <textarea
              value={reflection}
              onChange={(e) => setReflection(e.target.value)}
              placeholder={t("shutdownReflectionPlaceholder")}
              rows={2}
              maxLength={4000}
              className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
              style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
            />
          </div>
        </div>

        <DropAcknowledgement
          count={dropCount}
          checked={ackDrop}
          onChange={setAckDrop}
          label={t("dropAcknowledge", { n: dropCount })}
        />

        <div className="flex items-center gap-2 mt-4">
          <Button variant="ghost" size="sm" onClick={() => close(false)}>{t("shutdownNotYet")}</Button>
          <span className="flex-1" />
          <Button
            size="sm"
            onClick={apply}
            loading={applying}
            disabled={dropGateBlocks(dropCount, ackDrop)}
          >
            {t("shutdownConfirm")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
