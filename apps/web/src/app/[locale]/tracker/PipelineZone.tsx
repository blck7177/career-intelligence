"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import {
  getFunnel, listApplications, transitionApplication, updateApplication, createAction,
} from "@/api/client";
import type { FunnelResponse, ApplicationRead } from "@/api/client";
import { Button } from "@/components/ui/button";

/**
 * Plan · Pipeline zone. Funnel (with onsite target line) + advisory alerts
 * (ghosted suggestions confirm before applying — the audit-D gate) + the
 * planned-to-apply queue with inline excitement/lane and Apply/Drop/Tailor.
 */
export function PipelineZone() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [funnel, setFunnel] = useState<FunnelResponse | null>(null);
  const [planned, setPlanned] = useState<ApplicationRead[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = await getToken();
    const [f, p] = await Promise.all([
      getFunnel(token).catch(() => null),
      listApplications({ status_group: "planned", limit: 100 }, token).catch(() => ({ items: [], total: 0 })),
    ]);
    setFunnel(f);
    // Sort by excitement then freshness (newest first). Fit isn't on the list
    // row (detail-only), so ordering uses excitement + recency for now.
    const rows = [...p.items].sort(
      (a, b) => (b.excitement ?? 0) - (a.excitement ?? 0) ||
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
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

  async function applyToday(id: string) {
    setBusyId(id);
    try {
      const token = await getToken();
      await createAction({ type: "apply", title: t("applyTodayTitle"), application_id: id, due_at: new Date().toISOString() }, token);
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

  return (
    <section className="w-full space-y-4">
      <h2 className="text-sm font-semibold" style={{ color: "var(--ink-primary)" }}>{t("zonePipeline")}</h2>

      {/* Funnel */}
      <div className="rounded-lg border p-4" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-end gap-2">
          {stages.map((s) => (
            <div key={s.key} className="flex-1 min-w-0 text-center">
              <div className="flex items-end justify-center h-24">
                <div
                  className="w-full rounded-t"
                  style={{ height: `${Math.round((s.count / maxCount) * 100)}%`, minHeight: s.count > 0 ? 4 : 0, background: s.key === "onsite" ? "var(--match-strong-bg)" : "var(--primary)" }}
                  title={`${s.count}`}
                />
              </div>
              <div className="text-sm font-semibold tabular-nums mt-1" style={{ color: "var(--ink-primary)" }}>{s.count}</div>
              <div className="text-2xs truncate" style={{ color: "var(--ink-muted)" }}>{t(`funnelStage.${s.key}`)}</div>
            </div>
          ))}
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
                    {app.job?.company}<span className="mx-1">·</span>{t("seenOn", { date: ageOf(app.created_at) })}
                  </div>
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  {[1, 2, 3].map((n) => (
                    <button key={n} onClick={() => setStar(app, n)} aria-label={`${t("excitementLabel")} ${n}`} className="text-sm leading-none" style={{ color: n <= (app.excitement ?? 0) ? "var(--primary)" : "var(--ink-faint)" }}>★</button>
                  ))}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button size="sm" variant="outline" loading={busyId === app.id} onClick={() => applyToday(app.id)}>{t("applyToday")}</Button>
                  {app.job_id && (
                    <Link href={`/jobs?selected=${app.job_id}`} className="h-7 px-2 rounded-md text-xs font-medium flex items-center" style={{ border: "1px solid var(--border)", color: "var(--ink-secondary)" }}>
                      {t("tailor")}
                    </Link>
                  )}
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
