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
import { ZoneHead } from "./ZoneHead";

const DEFAULT_FRESH_DAYS = 3;
const ACTIVE_STAGES = ["applied", "in_review", "interviewing", "offer"];

/**
 * Plan · Pipeline zone. Funnel (with onsite highlight) + advisory alerts
 * (ghosted suggestions confirm before applying — the audit-D gate) + the
 * planned-to-apply queue: inline excitement, Apply now (opens the posting),
 * Job details, Drop.
 */
export function PipelineZone() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [funnel, setFunnel] = useState<FunnelResponse | null>(null);
  const [planned, setPlanned] = useState<ApplicationRead[] | null>(null);
  const [freshDays, setFreshDays] = useState(DEFAULT_FRESH_DAYS);
  const [onsiteTarget, setOnsiteTarget] = useState(4);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = await getToken();
    const [f, p, s] = await Promise.all([
      getFunnel(token).catch(() => null),
      listApplications({ status_group: "planned", limit: 100 }, token).catch(() => ({ items: [], total: 0 })),
      getPlannerSettings(token).catch(() => null),
    ]);
    setFunnel(f);
    setFreshDays(s?.fresh_window_days ?? DEFAULT_FRESH_DAYS);
    setOnsiteTarget(s?.onsite_target ?? 4);
    // Sort by excitement then recency — true posting date when known, else the
    // application's own age. Fit isn't on the list row (detail-only).
    const recency = (a: ApplicationRead) => new Date(a.job?.posted_at ?? a.created_at).getTime();
    const rows = [...p.items].sort(
      (a, b) => (b.excitement ?? 0) - (a.excitement ?? 0) || recency(b) - recency(a),
    );
    setPlanned(rows);
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  async function confirmGhost(id: string) {
    setBusyId(id);
    try {
      const token = await getToken();
      await transitionApplication(id, { status: "ghosted", force: false }, token);
      await load();
    } finally { setBusyId(null); }
  }

  async function drop(id: string) {
    setBusyId(id);
    try {
      const token = await getToken();
      await transitionApplication(id, { status: "withdrawn", force: false }, token);
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
              {al.kind === "ghosted_suggestion" && al.application_id && (
                <Button size="sm" variant="outline" loading={busyId === al.application_id} onClick={() => confirmGhost(al.application_id!)}>
                  {t("confirmGhosted")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Planned queue */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-muted)" }}>{t("plannedQueue")}</h3>
        {planned === null ? (
          <div className="animate-pulse h-16" aria-hidden />
        ) : planned.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("plannedEmpty")}</p>
        ) : (
          <ul className="space-y-1.5">
            {planned.map((app) => (
              <li key={app.id} className="flex items-center gap-2 py-1.5 border-b" style={{ borderColor: "var(--border)" }}>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate" style={{ color: "var(--ink-primary)" }}>{app.job?.title ?? "(untitled)"}</div>
                  <div className="text-2xs truncate" style={{ color: "var(--ink-muted)" }}>
                    {app.job?.company}<span className="mx-1">·</span>
                    {app.job?.posted_at
                      ? t("postedOn", { date: ageOf(app.job.posted_at) })
                      : t("seenOn", { date: ageOf(app.created_at) })}
                    {isFresh(app.job?.posted_at, freshDays) && (
                      <span className="ml-1.5 px-1 rounded-sm" style={{ background: "var(--match-good-bg)", color: "var(--match-good-fg)" }}>{t("fresh")}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  {[1, 2, 3].map((n) => (
                    <button key={n} onClick={() => setStar(app, n)} aria-label={`${t("excitementLabel")} ${n}`} className="text-sm leading-none" style={{ color: n <= (app.excitement ?? 0) ? "var(--primary)" : "var(--ink-faint)" }}>★</button>
                  ))}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {(app.job?.canonical_url ?? "").startsWith("http") && (
                    <a
                      href={app.job!.canonical_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="h-7 px-2 rounded-md text-xs font-medium flex items-center"
                      style={{ border: "1px solid var(--primary)", color: "var(--primary)" }}
                    >
                      {t("applyNow")}
                    </a>
                  )}
                  <Link href={`/jobs/${app.job_id}`} className="h-7 px-2 rounded-md text-xs font-medium flex items-center" style={{ border: "1px solid var(--border)", color: "var(--ink-secondary)" }}>
                    {t("jobDetails")}
                  </Link>
                  <Button size="sm" variant="ghost" loading={busyId === app.id} onClick={() => drop(app.id)}>{t("drop")}</Button>
                </div>
              </li>
            ))}
          </ul>
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

function ageOf(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400_000);
  return `${days}d`;
}

// A posting is "fresh" when its true posting date is within the window. Freshness
// needs a real posting date — the application's own age can't stand in, so an
// unknown posted_at is never fresh.
function isFresh(posted: string | null | undefined, windowDays: number): boolean {
  if (!posted) return false;
  const days = Math.floor((Date.now() - new Date(posted).getTime()) / 86400_000);
  return days >= 0 && days < windowDays;
}
