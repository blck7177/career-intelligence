"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import {
  getFunnel, getPlannerSettings, listApplications, transitionApplication, updateApplication,
} from "@/api/client";
import type { FunnelResponse, ApplicationRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { bandOf, BAND } from "@/lib/matchBand";
import { ZoneHead } from "@/components/ui/zone-head";

const DEFAULT_FRESH_DAYS = 3;
const DEFAULT_APPLY_OR_DROP = 14;
const ACTIVE_STAGES = ["applied", "in_review", "interviewing", "offer"];

/**
 * Plan · Pipeline zone. Funnel (horizontal, onsite target line) + advisory
 * alerts (read-only: a ghosted suggestion links to the application, it does not
 * apply itself) + the planned-to-apply queue as a table: Fit · excitement ·
 * lane cycle · age (posted/seen + fresh / apply-or-drop) · Apply now / Drop.
 * Sorted by freshness × fit × excitement.
 */
export function PipelineZone() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [funnel, setFunnel] = useState<FunnelResponse | null>(null);
  const [planned, setPlanned] = useState<ApplicationRead[] | null>(null);
  const [freshDays, setFreshDays] = useState(DEFAULT_FRESH_DAYS);
  const [onsiteTarget, setOnsiteTarget] = useState(4);
  const [applyOrDropDays, setApplyOrDropDays] = useState(DEFAULT_APPLY_OR_DROP);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = await getToken();
    const [f, p, s] = await Promise.all([
      getFunnel(token).catch(() => null),
      listApplications({ status_group: "planned", include_fit: true, limit: 100 }, token).catch(() => ({ items: [], total: 0 })),
      getPlannerSettings(token).catch(() => null),
    ]);
    setFunnel(f);
    const fresh = s?.fresh_window_days ?? DEFAULT_FRESH_DAYS;
    setFreshDays(fresh);
    setOnsiteTarget(s?.onsite_target ?? 4);
    setApplyOrDropDays(s?.apply_or_drop_days ?? DEFAULT_APPLY_OR_DROP);
    // Sort by freshness × fit × excitement (mockup order): fresh dominates, then
    // fit, then excitement.
    const score = (a: ApplicationRead) =>
      (isFresh(a.job?.posted_at, fresh) ? 1000 : 0) + (a.fit_score ?? 0) * 3 + (a.excitement ?? 0) * 25;
    setPlanned([...p.items].sort((a, b) => score(b) - score(a)));
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  async function drop(id: string) {
    setBusyId(id);
    try {
      const token = await getToken();
      // The note is what the timeline shows instead of a bare "status changed";
      // six months on, "dropped from the queue" is the difference between a
      // decision and an unexplained state change.
      await transitionApplication(id, { status: "withdrawn", force: false, note: t("dropNote") }, token);
      await load();
    } finally { setBusyId(null); }
  }

  async function setStar(app: ApplicationRead, n: number) {
    const next = app.excitement === n ? null : n;
    setPlanned((prev) => prev?.map((a) => (a.id === app.id ? { ...a, excitement: next } : a)) ?? null);
    try {
      const token = await getToken();
      await updateApplication(app.id, { excitement: next }, token);
    } catch { load(); }
  }

  async function cycleLane(app: ApplicationRead) {
    const next = app.lane === "a" ? "b" : app.lane === "b" ? "c" : app.lane === "c" ? null : "a";
    setPlanned((prev) => prev?.map((a) => (a.id === app.id ? { ...a, lane: next } : a)) ?? null);
    try {
      const token = await getToken();
      await updateApplication(app.id, { lane: next }, token);
    } catch { load(); }
  }

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

      {/* Planned queue — table: Job · Fit · Excite · Lane · Age · action */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide mb-2 flex items-baseline gap-1.5" style={{ color: "var(--ink-muted)" }}>
          {t("plannedQueue")}<span className="text-2xs normal-case font-normal" style={{ color: "var(--ink-faint)" }}>{t("plannedQueueSort")}</span>
        </h3>
        {planned === null ? (
          <div className="animate-pulse h-16" aria-hidden />
        ) : planned.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("plannedEmpty")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr className="text-2xs uppercase tracking-wide text-left" style={{ color: "var(--ink-faint)" }}>
                  <th className="font-semibold py-1.5 pr-2">{t("colJob")}</th>
                  <th className="font-semibold py-1.5 px-2">{t("colFit")}</th>
                  <th className="font-semibold py-1.5 px-2">{t("colExcite")}</th>
                  <th className="font-semibold py-1.5 px-2">{t("colLane")}</th>
                  <th className="font-semibold py-1.5 px-2">{t("colAge")}</th>
                  <th className="py-1.5 pl-2" />
                </tr>
              </thead>
              <tbody>
                {planned.map((app) => {
                  const posted = app.job?.posted_at;
                  const ageIso = posted ?? app.created_at;
                  const days = ageDays(ageIso);
                  const fresh = isFresh(posted, freshDays);
                  const stale = days >= applyOrDropDays;
                  const lane = laneStyle(app.lane);
                  const isHttp = (app.job?.canonical_url ?? "").startsWith("http");
                  return (
                    <tr key={app.id} className="border-t align-middle" style={{ borderColor: "var(--border)" }}>
                      {/* Job */}
                      <td className="py-2 pr-2 min-w-0" style={{ maxWidth: 240 }}>
                        <Link href={`/jobs/${app.job_id}`} className="block truncate font-medium hover:underline" style={{ color: "var(--ink-primary)" }}>
                          {app.job?.title ?? "(untitled)"}
                        </Link>
                        <span className="block truncate text-2xs" style={{ color: "var(--ink-muted)" }}>{app.job?.company}</span>
                      </td>
                      {/* Fit */}
                      <td className="py-2 px-2 whitespace-nowrap">
                        {typeof app.fit_score === "number" ? (
                          <span className="text-2xs font-bold px-1.5 py-0.5 rounded tabular-nums" style={{ background: BAND[bandOf(app.fit_score)].bg, color: BAND[bandOf(app.fit_score)].fg }}>
                            {app.fit_score}
                          </span>
                        ) : (
                          <span className="text-2xs" style={{ color: "var(--ink-faint)" }}>—</span>
                        )}
                      </td>
                      {/* Excitement */}
                      <td className="py-2 px-2 whitespace-nowrap">
                        <span className="flex items-center gap-0.5">
                          {[1, 2, 3].map((n) => (
                            <button key={n} onClick={() => setStar(app, n)} aria-label={`${t("excitementLabel")} ${n}`} className="text-sm leading-none" style={{ color: n <= (app.excitement ?? 0) ? "var(--primary)" : "var(--ink-faint)" }}>★</button>
                          ))}
                        </span>
                      </td>
                      {/* Lane cycle */}
                      <td className="py-2 px-2 whitespace-nowrap">
                        <button
                          onClick={() => cycleLane(app)}
                          aria-label={t("laneCycle")}
                          title={t("laneCycle")}
                          className="w-6 h-6 rounded-md text-2xs font-bold grid place-items-center"
                          style={{ background: lane.bg, color: lane.fg, border: `1px solid ${lane.border}` }}
                        >
                          {lane.label}
                        </button>
                      </td>
                      {/* Age */}
                      <td className="py-2 px-2 whitespace-nowrap text-2xs" style={{ color: "var(--ink-muted)" }}>
                        {posted ? t("postedOn", { date: `${days}d` }) : t("seenOn", { date: `${days}d` })}
                        {fresh && <span className="ml-1.5 px-1 rounded-sm" style={{ background: "var(--match-good-bg)", color: "var(--match-good-fg)" }}>{t("fresh")}</span>}
                        {!fresh && stale && <span className="ml-1.5 px-1 rounded-sm" style={{ background: "var(--match-partial-bg)", color: "var(--match-partial-fg)" }}>{t("applyOrDrop")}</span>}
                      </td>
                      {/* Actions */}
                      <td className="py-2 pl-2 whitespace-nowrap text-right">
                        <span className="inline-flex items-center gap-1">
                          {isHttp && (
                            <a href={app.job!.canonical_url} target="_blank" rel="noopener noreferrer" className="h-7 px-2 rounded-md text-xs font-medium inline-flex items-center" style={{ border: "1px solid var(--primary)", color: "var(--primary)" }}>
                              {t("applyNow")}
                            </a>
                          )}
                          <Button size="sm" variant="ghost" loading={busyId === app.id} onClick={() => drop(app.id)}>{t("drop")}</Button>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Networking — deferred feature, placeholder (see exec_plan W2-C1 rule 4) */}
      <div className="rounded-lg border border-dashed p-3 opacity-60" style={{ borderColor: "var(--border)" }}>
        <div className="text-xs font-semibold" style={{ color: "var(--ink-muted)" }}>{t("networkingTitle")}</div>
        <div className="text-2xs mt-0.5" style={{ color: "var(--ink-faint)" }}>{t("networkingSoon")}</div>
      </div>
    </section>
  );
}

function ageDays(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400_000);
}

// A posting is "fresh" when its true posting date is within the window. Freshness
// needs a real posting date — the application's own age can't stand in, so an
// unknown posted_at is never fresh.
function isFresh(posted: string | null | undefined, windowDays: number): boolean {
  if (!posted) return false;
  const days = Math.floor((Date.now() - new Date(posted).getTime()) / 86400_000);
  return days >= 0 && days < windowDays;
}

function laneStyle(lane: string | null | undefined): { label: string; bg: string; fg: string; border: string } {
  switch (lane) {
    case "a": return { label: "A", bg: "var(--match-good-bg)", fg: "var(--match-good-fg)", border: "var(--match-good-fg)" };
    case "b": return { label: "B", bg: "var(--match-partial-bg)", fg: "var(--match-partial-fg)", border: "var(--match-partial-fg)" };
    case "c": return { label: "C", bg: "var(--muted)", fg: "var(--ink-secondary)", border: "var(--border)" };
    default: return { label: "–", bg: "transparent", fg: "var(--ink-faint)", border: "var(--border)" };
  }
}
