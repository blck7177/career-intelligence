"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import type { ApplicationRead } from "@/api/client";
import { AddApplicationEntry } from "./AddApplicationEntry";
import { STATUS_STYLE } from "./status";
import { bandOf, BAND } from "@/lib/matchBand";
import { matchesQuery, type ApplicationsList } from "./useApplicationsList";
import { rankedIds } from "./queueRank";

/**
 * Every application, beside the day's plan.
 *
 * The Plan view is where the day gets decided, and until now deciding anything
 * about a specific application meant leaving it for a separate tab. The two
 * lists that tab held — what is in flight and what is queued to apply to — are
 * the same two lists the plan is made against, so they belong on the same
 * screen as the plan.
 *
 * Rows open a panel rather than navigating: this is context for a decision
 * being made on the left, and a full page turn loses the day you were planning.
 */
export function Sidebar({
  data,
  freshDays,
  selectedId,
  onSelect,
}: {
  data: ApplicationsList;
  /** settings.fresh_window_days — drives the queue's ranking. */
  freshDays: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations("tracker");
  const [query, setQuery] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const { active, planned, closed, loaded, error, reload } = data;

  // Ranked once per fetch, not per render: rating a row rewrites it, and
  // re-sorting mid-gesture moves the next row under the cursor.
  const queueOrder = useMemo(() => rankedIds(planned, freshDays), [planned, freshDays]);
  const queue = useMemo(() => {
    const byId = new Map(planned.map((a) => [a.id, a]));
    return queueOrder.map((id) => byId.get(id)).filter((a): a is ApplicationRead => !!a);
  }, [planned, queueOrder]);

  const f = (rows: ApplicationRead[]) => rows.filter((a) => matchesQuery(a, query));
  const shownActive = f(active);
  const shownQueue = f(queue);
  const shownClosed = f(closed);

  return (
    <aside className="flex flex-col gap-2.5 min-[1100px]:sticky min-[1100px]:top-2">
      <div className="flex items-center gap-2">
        <AddApplicationEntry onAdded={(id) => { void reload(); onSelect(id); }} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("sidebarSearch")}
          className="flex-1 min-w-0 h-8 px-2.5 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
          style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
        />
      </div>

      {error && (
        <p className="text-xs px-1" style={{ color: "var(--danger-fg)" }}>{t("sidebarLoadFailed")}</p>
      )}

      <Group title={t("sidebarActive")} count={shownActive.length} loaded={loaded}>
        {shownActive.map((a) => (
          <Row key={a.id} a={a} selected={a.id === selectedId} onSelect={onSelect} kind="active" t={t} />
        ))}
      </Group>

      <Group title={t("sidebarQueue")} count={shownQueue.length} loaded={loaded}>
        {shownQueue.map((a) => (
          <Row key={a.id} a={a} selected={a.id === selectedId} onSelect={onSelect} kind="queue" t={t} />
        ))}
      </Group>

      {closed.length > 0 && (
        <div
          className="rounded-xl border"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <button
            type="button"
            className="w-full flex items-baseline gap-1.5 px-3 py-2 text-2xs font-bold uppercase tracking-wider"
            style={{ color: "var(--ink-muted)" }}
            onClick={() => setShowClosed((v) => !v)}
            aria-expanded={showClosed}
          >
            {t("sidebarClosed")}
            <span className="ml-auto tabular-nums">{shownClosed.length}</span>
            <span aria-hidden>{showClosed ? "⌃" : "⌄"}</span>
          </button>
          {showClosed && (
            <div className="px-1.5 pb-1.5">
              {shownClosed.map((a) => (
                <Row key={a.id} a={a} selected={a.id === selectedId} onSelect={onSelect} kind="closed" t={t} />
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

function Group({
  title, count, loaded, children,
}: {
  title: string;
  count: number;
  loaded: boolean;
  children: React.ReactNode;
}) {
  const empty = loaded && count === 0;
  return (
    <div
      className="rounded-xl border px-1.5 pt-2 pb-1.5"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
      <div
        className="flex items-baseline gap-1.5 px-1.5 pb-1.5 text-2xs font-bold uppercase tracking-wider"
        style={{ color: "var(--ink-muted)" }}
      >
        {title}
        <span className="ml-auto tabular-nums">{loaded ? count : ""}</span>
      </div>
      {!loaded ? (
        <div className="h-14 animate-pulse rounded-lg mx-1.5 mb-1" style={{ background: "var(--muted)" }} aria-hidden />
      ) : empty ? null : (
        children
      )}
    </div>
  );
}

function Row({
  a, selected, onSelect, kind, t,
}: {
  a: ApplicationRead;
  selected: boolean;
  onSelect: (id: string) => void;
  kind: "active" | "queue" | "closed";
  t: ReturnType<typeof useTranslations>;
}) {
  const style = STATUS_STYLE[a.status] ?? STATUS_STYLE.planned;
  // What happens next, for rows where something is owed. The queue ranks by
  // fit and excitement instead — a row you have not applied to has no next step
  // beyond applying.
  //
  // The key is built from the type, so every member of ActionType (see
  // contracts/api/applications.py) needs an entry under tracker.actionType —
  // including "custom", which is what a hand-written to-do gets. next-intl
  // renders a missing key as the key itself, and no test catches a dynamic one.
  const next = kind === "active" && a.next_action_type
    ? t(`actionType.${a.next_action_type}` as never)
    : null;

  return (
    <button
      type="button"
      onClick={() => onSelect(a.id)}
      className="w-full text-left rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]"
      style={{ background: selected ? "var(--accent)" : undefined }}
    >
      <span className="flex items-center gap-1.5 text-xs">
        <span className="font-semibold truncate" style={{ color: "var(--ink-primary)" }}>
          {a.job?.company ?? "—"}
        </span>
        <span className="truncate flex-1" style={{ color: "var(--ink-muted)" }}>
          {a.job?.title ?? ""}
        </span>
        {kind === "queue" && typeof a.fit_score === "number" && (
          <span
            className="shrink-0 px-1 rounded text-[10px] font-bold tabular-nums"
            style={{ background: BAND[bandOf(a.fit_score)].bg, color: BAND[bandOf(a.fit_score)].fg }}
          >
            {a.fit_score}
          </span>
        )}
        {kind === "queue" && (a.excitement ?? 0) > 0 && (
          <span className="shrink-0 text-[10px]" style={{ color: "var(--warn-fg)" }}>
            {"★".repeat(a.excitement ?? 0)}
          </span>
        )}
        {kind !== "queue" && (
          <span
            className="shrink-0 px-1 rounded text-[10px] font-semibold"
            style={{ background: style.bg, color: style.fg }}
          >
            {t(`status.${a.status}`)}
          </span>
        )}
      </span>
      {next && (
        <span className="block text-[10px] mt-0.5 truncate" style={{ color: "var(--ink-faint)" }}>
          └ {next}
        </span>
      )}
    </button>
  );
}
