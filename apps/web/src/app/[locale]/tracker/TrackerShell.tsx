"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { optionPillVariants } from "@/components/ui/option-pill-variants";
import { ApplicationsMasterDetail, type AppRow, type AppCounts } from "./ApplicationsMasterDetail";
import { PlanView } from "./PlanView";

interface Props {
  applications: AppRow[];
  group: string;
  needsAction: boolean;
  totalCount: number;
  currentPage: number;
  totalPages: number;
  counts: AppCounts | null;
}

/** Tracker tab: two sub-views (Applications | Plan). P0 ships Applications;
 *  the Plan view (Today list, pipeline health, weekly targets) lands in P1. */
export function TrackerShell(props: Props) {
  const t = useTranslations("tracker");
  // Default to Plan — "open to what to do today" (decision point 2).
  const [view, setView] = useState<"applications" | "plan">("plan");

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div
        className="shrink-0 flex items-center gap-1.5 px-[var(--space-row-edge)] pt-3 pb-2"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <button
          className={optionPillVariants({ selected: view === "applications", className: "!h-7 !px-3 !text-xs" })}
          onClick={() => setView("applications")}
        >
          {t("viewApplications")}
        </button>
        <button
          className={optionPillVariants({ selected: view === "plan", className: "!h-7 !px-3 !text-xs" })}
          onClick={() => setView("plan")}
        >
          {t("viewPlan")}
        </button>
      </div>

      {view === "applications" ? (
        <ApplicationsMasterDetail {...props} />
      ) : (
        <PlanView />
      )}
    </div>
  );
}
