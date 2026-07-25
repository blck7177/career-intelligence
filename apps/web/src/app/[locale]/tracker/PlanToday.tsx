"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { listActions, createAction, updateAction } from "@/api/client";
import type { ActionRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";

type Bucket = "overdue" | "today" | "upcoming" | "anytime";
const ORDER: Bucket[] = ["overdue", "today", "upcoming", "anytime"];
const HORIZON_DAYS = 14;

/**
 * P0 Plan view: the "Today" list only. Pending actions within a 14-day horizon
 * (plus undated), bucketed overdue/today/upcoming/anytime, with complete/snooze
 * and a manual add. Weekly targets, pipeline health, and the planned queue are
 * P1 (they need the rules engine). Action rows are populated manually at P0.
 */
export function PlanToday() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [actions, setActions] = useState<ActionRead[] | null>(null);
  const [error, setError] = useState(false);
  const [title, setTitle] = useState("");
  const [adding, setAdding] = useState(false);
  // Ids optimistically removed but whose mutation is still in flight — filtered
  // out of any concurrent load() so a refetch can't resurrect a row the user
  // just completed/snoozed before its API call settles.
  const removingRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const horizon = new Date(Date.now() + HORIZON_DAYS * 86400_000).toISOString();
      const res = await listActions({ due_on_or_before: horizon, include_undated: true }, token);
      setActions(res.items.filter((a) => !removingRef.current.has(a.id)));
      setError(false);
    } catch {
      setError(true);
    }
  }, [getToken]);

  useEffect(() => {
    load();
  }, [load]);

  function bucketOf(a: ActionRead): Bucket {
    if (!a.due_at) return "anytime";
    const now = new Date();
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    // Next local midnight via the Date constructor (handles 23/24/25h DST days),
    // not a fixed +24h which drifts the today/upcoming split on transition days.
    const endToday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime();
    const d = new Date(a.due_at).getTime();
    if (d < startToday) return "overdue";
    if (d < endToday) return "today";
    return "upcoming";
  }

  async function mutate(id: string, op: "complete" | "snooze") {
    removingRef.current.add(id);
    setActions((prev) => prev?.filter((a) => a.id !== id) ?? null); // optimistic
    try {
      const token = await getToken();
      await updateAction(id, { op, snooze_days: 1 }, token);
    } catch {
      load(); // reconcile on failure (removingRef still guards the in-flight window)
    } finally {
      removingRef.current.delete(id);
    }
  }

  async function add() {
    if (adding) return; // in-flight guard (Enter can fire faster than the disabled button)
    const title_ = title.trim();
    if (!title_) return;
    setAdding(true);
    try {
      const token = await getToken();
      await createAction({ type: "custom", title: title_ }, token);
      setTitle("");
      await load();
    } catch {
      // leave the typed title in place so the user can retry; no row was created
    } finally {
      setAdding(false);
    }
  }

  const grouped: Record<Bucket, ActionRead[]> = { overdue: [], today: [], upcoming: [], anytime: [] };
  for (const a of actions ?? []) grouped[bucketOf(a)].push(a);
  const isEmpty = actions !== null && actions.length === 0;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-[var(--space-row-edge)] py-6 space-y-6">
        {/* Manual add — always available, even in the error state */}
        <div className="flex items-center gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !adding) add();
            }}
            placeholder={t("actionTitlePlaceholder")}
            className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
            style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
          />
          <Button size="sm" onClick={add} disabled={!title.trim()} loading={adding}>{t("add")}</Button>
        </div>

        {actions === null ? (
          error ? (
            <div className="text-center py-8">
              <p className="text-sm mb-3" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
              <Button size="sm" variant="outline" onClick={load}>{t("retry")}</Button>
            </div>
          ) : (
            <div className="animate-pulse h-24" aria-hidden />
          )
        ) : isEmpty ? (
          <p className="text-sm text-center py-8" style={{ color: "var(--ink-muted)" }}>{t("todayEmpty")}</p>
        ) : (
          ORDER.filter((b) => grouped[b].length > 0).map((b) => (
            <section key={b}>
              <h2
                className="text-xs font-semibold uppercase tracking-wide mb-2"
                style={{ color: b === "overdue" ? "#991b1b" : "var(--ink-muted)" }}
              >
                {t(`group.${b}`)}
              </h2>
              <ul className="space-y-1.5">
                {grouped[b].map((a) => (
                  <li
                    key={a.id}
                    className="flex items-center justify-between gap-2 py-1.5 border-b"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <span className="min-w-0 truncate text-sm" style={{ color: "var(--ink-secondary)" }}>
                      {a.auto_generated && (
                        <span
                          className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle"
                          style={{ background: "var(--primary)" }}
                          title={t("autoGenerated")}
                          aria-label={t("autoGenerated")}
                        />
                      )}
                      {a.title}
                      {a.due_at && <span className="ml-2 text-2xs" style={{ color: "var(--ink-faint)" }}>{fmtTs(a.due_at)}</span>}
                    </span>
                    <span className="shrink-0 flex items-center gap-1">
                      <Button size="sm" variant="ghost" onClick={() => mutate(a.id, "snooze")}>{t("snooze")}</Button>
                      <Button size="sm" variant="outline" onClick={() => mutate(a.id, "complete")}>{t("complete")}</Button>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
