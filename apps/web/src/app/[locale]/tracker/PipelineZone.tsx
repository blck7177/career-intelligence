"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import type { PlannerData } from "./usePlannerData";
import { buttonVariants } from "@/components/ui/button-variants";
import { ZoneHead } from "@/components/ui/zone-head";

const ACTIVE_STAGES = ["applied", "in_review", "interviewing", "offer"];

/**
 * Plan · Pipeline zone. Funnel (horizontal, onsite target line) + advisory
 * alerts (read-only: a ghosted suggestion links to the application, it does not
 * apply itself).
 *
 * It used to carry the planned-to-apply queue as a table as well. The sidebar
 * now lists that queue in the same ranked order beside the day being planned,
 * so this zone is what it always claimed to be in its title: how the pipeline
 * is doing, not what to do next. Health reads; the sidebar acts.
 */
export function PipelineZone({ data }: { data: PlannerData }) {
  const t = useTranslations("tracker");
  // The funnel and the settings come from the Plan view's single store. This
  // zone used to fetch its own copy of both, which meant the alerts it renders
  // and the identical alerts in Today's rail were two independent readings:
  // acting in either place left the other showing the old one, in both
  // directions.
  const { funnel, settings } = data;

  const onsiteTarget = settings?.onsite_target ?? 4;

  const stages = funnel?.stages ?? [];
  const alerts = funnel?.alerts ?? [];
  const maxCount = Math.max(1, ...stages.map((s) => s.count));
  const stageCount = (k: string) => stages.find((s) => s.key === k)?.count ?? 0;
  const activeN = ACTIVE_STAGES.reduce((n, k) => n + stageCount(k), 0);
  const zoneSub = funnel ? t("pipelineSub", { active: activeN, planned: stageCount("planned") }) : undefined;

  return (
    <section className="w-full space-y-4">
      <ZoneHead eyebrow={t("zoneEyebrowPipeline")} title={t("pipelineTitle")} sub={zoneSub} />

      {/* Funnel — horizontal bars, one row per stage; onsite shows its target */}
      <div className="rounded-lg border p-4" style={{ borderColor: "var(--border)" }}>
        <div className="space-y-2">
          {stages.map((s) => {
            const pct = Math.round((s.count / maxCount) * 100);
            const isOnsite = s.key === "onsite";
            return (
              <div key={s.key} className="grid items-center gap-2.5" style={{ gridTemplateColumns: "84px 1fr auto" }}>
                <span className="text-2xs truncate" style={{ color: "var(--ink-muted)" }}>{t(`funnelStage.${s.key}`)}</span>
                <span className="h-2.5 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${pct}%`, minWidth: s.count > 0 ? 6 : 0, background: isOnsite ? "var(--match-good-fg)" : "var(--primary)" }}
                  />
                </span>
                <span className="text-xs font-semibold tabular-nums text-right whitespace-nowrap" style={{ color: "var(--ink-primary)" }}>
                  {s.count}
                  {isOnsite && <span className="font-normal text-2xs" style={{ color: "var(--ink-faint)" }}> / {onsiteTarget}</span>}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <ul className="space-y-1.5">
          {alerts.map((al, i) => (
            <li
              key={i}
              className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
              style={{ borderColor: al.severity === "warn" ? "#f59e0b55" : "var(--border)", background: al.severity === "warn" ? "#fffbeb" : "transparent" }}
            >
              <span style={{ color: "var(--ink-secondary)" }}>{t(al.message_key, al.context as Record<string, string | number>)}</span>
              {/* An advisory line does not get to fire an irreversible mutation.
                  Marking ghosted is terminal — every move out of it needs
                  force — so this hands off to the application's own page, where
                  the timeline, the last contact and the close buttons are all
                  in view. (planner_ux_research_0726.html:596 offers exactly two
                  remedies for an irreversible action in a list: move it to L3,
                  or gate it. This is the first.) */}
              {al.kind === "ghosted_suggestion" && al.application_id && (
                <Link
                  href={`/tracker/${al.application_id}`}
                  className={buttonVariants({ size: "sm", variant: "outline" })}
                >
                  {t("alertReview")}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Networking — deferred feature, placeholder (see exec_plan W2-C1 rule 4) */}
      <div className="rounded-lg border border-dashed p-3 opacity-60" style={{ borderColor: "var(--border)" }}>
        <div className="text-xs font-semibold" style={{ color: "var(--ink-muted)" }}>{t("networkingTitle")}</div>
        <div className="text-2xs mt-0.5" style={{ color: "var(--ink-faint)" }}>{t("networkingSoon")}</div>
      </div>
    </section>
  );
}
