"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ClipboardList } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { optionPillVariants } from "@/components/ui/option-pill-variants";
import { EmptyState } from "@/components/EmptyState";
import { AddApplicationEntry } from "./AddApplicationEntry";
import { PlanView } from "./PlanView";
import { ScheduleView } from "./ScheduleView";
import { SettingsView } from "./SettingsView";
import { PageHeader } from "./PageHeader";

/** Tracker tab: three sub-views (Plan | Week | Settings). Default is Plan —
 *  "open to what to do today". Week is the schedule grid; Settings edits the
 *  planner config.
 *
 *  There was a fourth, Applications, holding a list of every application beside
 *  a detail pane. Both halves now exist inside Plan — the lists as the sidebar,
 *  the detail as the panel a row opens — so keeping the tab meant maintaining a
 *  second place to read the same rows, and making the user pick one.
 *
 *  @param empty no applications in this workspace at all (server-measured).
 */
export function TrackerShell({ empty }: { empty: boolean }) {
  const t = useTranslations("tracker");
  // Default to Plan — "open to what to do today" (decision point 2).
  const [view, setView] = useState<"plan" | "schedule" | "settings">("plan");
  // What was added from the first-run state, so the plan opens with it already
  // showing. Leaving the empty state is a separate flag on purpose: it waits for
  // the add panel's confirmation to finish, because switching on `added` would
  // unmount that panel the instant it had something to say. Neither reading is
  // the server's — `empty` was measured before the add, and asking again to
  // learn what we just did would hold a blank screen for a round trip.
  const [added, setAdded] = useState<string | null>(null);
  const [leftEmpty, setLeftEmpty] = useState(false);

  // Switching sub-views spends the seed. PlanView reads it once, when it mounts,
  // and this is a plain conditional render — so leaving Plan unmounts it and
  // coming back re-seeds from the same id, re-opening a panel the user had
  // already closed, for the rest of the session.
  function show(next: "plan" | "schedule" | "settings") {
    if (next !== "plan") setAdded(null);
    setView(next);
  }

  // Nothing tracked yet — the invitation, not an empty desk with three tabs on
  // it. (Deliberately outside the header/tab chrome, as it was when this lived
  // in the page: there is nothing yet for the tabs to switch between.)
  if (empty && !leftEmpty) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <EmptyState
          icon={ClipboardList}
          title={t("emptyTitle")}
          action={
            <div className="flex flex-col items-center gap-3">
              <AddApplicationEntry onAdded={setAdded} onDone={() => setLeftEmpty(true)} />
              <Link
                href="/jobs"
                className="inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
                style={{ color: "var(--primary)" }}
              >
                {t("goToJobs")}
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <PageHeader />
      <div
        className="shrink-0 flex items-center gap-1.5 px-[var(--space-row-edge)] pt-2 pb-2"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <button
          className={optionPillVariants({ selected: view === "plan", className: "!h-7 !px-3 !text-xs" })}
          onClick={() => show("plan")}
        >
          {t("viewPlan")}
        </button>
        <button
          className={optionPillVariants({ selected: view === "schedule", className: "!h-7 !px-3 !text-xs" })}
          onClick={() => show("schedule")}
        >
          {t("viewSchedule")}
        </button>
        <button
          className={optionPillVariants({ selected: view === "settings", className: "!h-7 !px-3 !text-xs" })}
          onClick={() => show("settings")}
        >
          {t("viewSettings")}
        </button>
      </div>

      {view === "plan" ? (
        <PlanView onOpenSchedule={() => show("schedule")} initialSelectedId={added} />
      ) : view === "schedule" ? (
        <ScheduleView />
      ) : (
        <SettingsView />
      )}
    </div>
  );
}
