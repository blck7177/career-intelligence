"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useApiToken } from "@/hooks/useApiToken";
import {
  addApplicationEvent, getApplication, getPlannerSettings, getPlannerWeek, updateAction,
} from "@/api/client";
import { fmtTs } from "@/lib/utils";
import { localMidnightUtc, addDays, localDateOf } from "@/lib/quickParse";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toaster";
import { optionPillVariants } from "@/components/ui/option-pill-variants";
import { EmptyState } from "@/components/EmptyState";
import { ClipboardList } from "lucide-react";
import { ApplicationDetailPane } from "./ApplicationDetailPane";
import { AddApplicationEntry } from "./AddApplicationEntry";
import { STATUS_STYLE } from "./status";

export interface AppRow {
  id: string;
  status: string;
  lane: string | null;
  excitement: number | null;
  applied_at: string | null;
  next_action_due_at: string | null;
  next_action_type: string | null;
  created_at: string;
  jobTitle: string;
  company: string;
}

/** Workspace-wide per-group counts for the filter pills (from the summary
 *  endpoint — independent of the current filtered page). */
export interface AppCounts {
  all: number;
  active: number;
  planned: number;
  closed: number;
  needsAction: number;
}

interface Props {
  applications: AppRow[];
  group: string; // all | planned | active | closed
  needsAction: boolean;
  totalCount: number;
  currentPage: number;
  totalPages: number;
  counts: AppCounts | null;
}

const LG = "(min-width: 1024px)";

const GROUP_FILTERS: { key: string; group: string }[] = [
  { key: "filterAll", group: "all" },
  { key: "filterActive", group: "active" },
  { key: "filterPlanned", group: "planned" },
  { key: "filterClosed", group: "closed" },
];

function pageNumbers(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set([1, 2, total - 1, total, current - 1, current, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result: (number | "ellipsis")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (prev && p - prev > 1) result.push("ellipsis");
    result.push(p);
    prev = p;
  }
  return result;
}

export function ApplicationsMasterDetail({
  applications,
  group,
  needsAction,
  totalCount,
  currentPage,
  totalPages,
  counts,
}: Props) {
  const t = useTranslations("tracker");
  const router = useRouter();
  const searchParams = useSearchParams();
  const isDesktop = useMediaQuery(LG);
  const getToken = useApiToken();

  // Bumped when a row action mutates the application the pane is showing.
  const [paneKey, setPaneKey] = useState(0);

  // Selection: local state is source of truth, ?selected= synced via History API.
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get("selected"));
  const selectedValid =
    selectedId && applications.some((a) => a.id === selectedId) ? selectedId : null;
  const selectedForPane = selectedValid ?? (isDesktop ? applications[0]?.id ?? null : null);

  useEffect(() => {
    if (!isDesktop || selectedValid) return;
    const first = applications[0]?.id ?? null;
    setSelectedId(first);
    const params = new URLSearchParams(window.location.search);
    if (first) params.set("selected", first);
    else params.delete("selected");
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  }, [isDesktop, selectedValid, applications]);

  useEffect(() => {
    const onPop = () => setSelectedId(new URLSearchParams(window.location.search).get("selected"));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const selectRow = useCallback((id: string) => {
    setSelectedId(id);
    const params = new URLSearchParams(window.location.search);
    params.set("selected", id);
    window.history.pushState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, []);

  const handleAdded = useCallback(
    (id: string) => {
      selectRow(id);
      router.refresh(); // re-fetch the server list so the new row appears
    },
    [selectRow, router],
  );

  const openRow = useCallback(
    (id: string) => {
      if (isDesktop) selectRow(id);
      else router.push(`/tracker/${id}`);
    },
    [isDesktop, selectRow, router],
  );

  function groupHref(g: string): string {
    const params = new URLSearchParams(searchParams.toString());
    if (g === "all") params.delete("group");
    else params.set("group", g);
    params.delete("needs_action");
    params.delete("page");
    params.delete("selected");
    const s = params.toString();
    return s ? `/tracker?${s}` : "/tracker";
  }

  function needsActionHref(): string {
    const params = new URLSearchParams(searchParams.toString());
    if (needsAction) params.delete("needs_action");
    else params.set("needs_action", "1");
    params.delete("group");
    params.delete("page");
    params.delete("selected");
    const s = params.toString();
    return s ? `/tracker?${s}` : "/tracker";
  }

  function pageHref(p: number): string {
    const params = new URLSearchParams(searchParams.toString());
    if (p <= 1) params.delete("page");
    else params.set("page", String(p));
    params.delete("selected");
    const s = params.toString();
    return s ? `/tracker?${s}` : "/tracker";
  }

  return (
    <div className="flex-1 min-h-0 flex">
      {/* ── Left: list column ── */}
      <div className="flex flex-col w-full lg:w-[360px] xl:w-[400px] lg:shrink-0 min-h-0 lg:border-r border-[var(--border)]">
        <div className="shrink-0 px-[var(--space-row-edge)] pt-4 pb-3 space-y-3" style={{ borderBottom: "1px solid var(--border)" }}>
          <h1 className="text-base font-semibold flex items-baseline gap-2" style={{ color: "var(--ink-primary)" }}>
            {t("title")}
            <span className="text-xs font-normal" style={{ color: "var(--ink-muted)" }}>
              {t("count", { count: totalCount })}
            </span>
          </h1>
          <div className="flex flex-wrap items-center gap-1.5">
            {GROUP_FILTERS.map(({ key, group: g }) => (
              <Link
                key={g}
                href={groupHref(g)}
                className={optionPillVariants({ selected: !needsAction && group === g, className: "!h-7 !px-2.5 !text-xs" })}
              >
                {t(key)}
                {counts ? (
                  <span className="ml-1 tabular-nums" style={{ opacity: 0.55 }}>
                    {counts[g as keyof AppCounts]}
                  </span>
                ) : null}
              </Link>
            ))}
            <div className="w-px self-stretch bg-[var(--border)] mx-0.5" />
            <Link
              href={needsActionHref()}
              className={optionPillVariants({ selected: needsAction, className: "!h-7 !px-2.5 !text-xs" })}
            >
              {t("filterNeedsAction")}
              {counts ? (
                <span className="ml-1 tabular-nums" style={{ opacity: 0.55 }}>
                  {counts.needsAction}
                </span>
              ) : null}
            </Link>
          </div>
          <AddApplicationEntry onAdded={handleAdded} />
        </div>

        {applications.length === 0 ? (
          <div className="flex-1 min-h-0 flex items-center justify-center p-6">
            <EmptyState icon={ClipboardList} title={t("emptyFiltered")} />
          </div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto">
            {applications.map((app) => (
              <AppListRow
                key={app.id}
                app={app}
                isViewed={isDesktop && selectedForPane === app.id}
                statusLabel={t(`status.${app.status}`)}
                subline={sublineFor(app, t)}
                onOpen={() => openRow(app.id)}
                onMutated={() => {
                  router.refresh();
                  // The pane fetches its own copy of this application; the
                  // server-list refresh above does not reach it.
                  if (app.id === selectedForPane) setPaneKey((n) => n + 1);
                }}
              />
            ))}
          </div>
        )}

        {totalPages > 1 && (
          <div className="shrink-0 flex items-center justify-center gap-1 px-2 py-2.5" style={{ borderTop: "1px solid var(--border)" }}>
            <Link
              href={pageHref(currentPage - 1)}
              aria-disabled={currentPage === 1}
              className="h-7 px-2 rounded-md text-xs font-medium flex items-center"
              style={currentPage === 1 ? { color: "var(--muted-foreground)", pointerEvents: "none", opacity: 0.4 } : { color: "var(--foreground)", border: "1px solid var(--border)" }}
            >
              {t("prev")}
            </Link>
            {pageNumbers(currentPage, totalPages).map((p, idx) =>
              p === "ellipsis" ? (
                <span key={`e${idx}`} className="px-1 text-xs" style={{ color: "var(--muted-foreground)" }}>…</span>
              ) : (
                <Link
                  key={p}
                  href={pageHref(p)}
                  className="h-7 w-7 rounded-md text-xs font-medium flex items-center justify-center tabular-nums"
                  style={p === currentPage ? { background: "var(--ink-primary)", color: "#fff" } : { color: "var(--foreground)", border: "1px solid var(--border)" }}
                >
                  {p}
                </Link>
              ),
            )}
            <Link
              href={pageHref(currentPage + 1)}
              aria-disabled={currentPage === totalPages}
              className="h-7 px-2 rounded-md text-xs font-medium flex items-center"
              style={currentPage === totalPages ? { color: "var(--muted-foreground)", pointerEvents: "none", opacity: 0.4 } : { color: "var(--foreground)", border: "1px solid var(--border)" }}
            >
              {t("next")}
            </Link>
          </div>
        )}
      </div>

      {/* ── Right: detail pane (desktop only) ── */}
      <div className="hidden lg:flex flex-1 min-w-0 min-h-0">
        <ApplicationDetailPane
          applicationId={selectedForPane}
          onListChanged={() => router.refresh()}
          refreshKey={paneKey}
        />
      </div>
    </div>
  );
}

function sublineFor(app: AppRow, t: ReturnType<typeof useTranslations>): string {
  if (app.next_action_due_at) {
    const ty = app.next_action_type;
    // Semantic phrase for typed auto-actions ("follow-up due …"); manual
    // actions (type "custom") fall back to the plain "next: …" wording.
    if (ty && ty !== "custom") {
      return t("nextActionTyped", { type: t(`actionType.${ty}`), date: fmtTs(app.next_action_due_at) });
    }
    return t("nextActionDue", { date: fmtTs(app.next_action_due_at) });
  }
  if (app.applied_at) return t("appliedOn", { date: fmtTs(app.applied_at) });
  return t("seenOn", { date: fmtTs(app.created_at) });
}

interface RowProps {
  app: AppRow;
  isViewed: boolean;
  statusLabel: string;
  subline: string;
  onOpen: () => void;
  /** Absolute target for "reschedule", or null while it is unknown — see the
   *  comment where it is computed. */
  onMutated: () => void;
}

/**
 * A row, plus the two things people do to a list of applications without
 * wanting to open anything: jot down what just happened, and push the next
 * to-do out a day. Both appear on hover (and on keyboard focus) and both stop
 * the click from also selecting the row.
 */
function AppListRow({ app, isViewed, statusLabel, subline, onOpen, onMutated }: RowProps) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const style = STATUS_STYLE[app.status] ?? STATUS_STYLE.planned;
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"note" | "defer" | null>(null);

  async function saveNote() {
    const msg = note.trim();
    if (!msg || busy) return;
    setBusy("note");
    try {
      const token = await getToken();
      await addApplicationEvent(app.id, { message: msg }, token);
      setNote("");
      setNoting(false);
      toast(t("rowNoteSaved"));
      onMutated();
    } catch {
      // Keep the text and the box open so it can be retried; say so, because a
      // silent no-op here loses what the user typed.
      toast.error(t("rowActionFailed"));
    } finally {
      setBusy(null);
    }
  }

  /**
   * Push this application's next to-do out by a day.
   *
   * "Next" uses the same predicate the row's own subline does — pending, dated,
   * soonest first (`earliest_pending_action_map`), with the id as the tie-break
   * the query now also declares — so the thing that moves is the thing the row
   * is showing, even when two to-dos fall due on the same day.
   *
   * The target is absolute, because the repository measures a relative snooze
   * from due_at and an overdue item would stay overdue. It is anchored on the
   * LATER of today and the to-do's own due date, so this only ever pushes out:
   * the first version always sent tomorrow, which quietly pulled a to-do due
   * next week FORWARD — and the snooze counter, which only counts real
   * postponement, stayed silent about it.
   *
   * Today and the timezone are read at click time, not at mount. Caching them
   * froze "tomorrow" at page load, and this is a day planner whose own shutdown
   * ritual has a branch for sessions that cross midnight.
   */
  async function reschedule() {
    if (busy) return;
    setBusy("defer");
    try {
      const token = await getToken();
      const [wk, cfg, detail] = await Promise.all([
        getPlannerWeek(undefined, token),
        getPlannerSettings(token),
        getApplication(app.id, token),
      ]);
      const today = wk.days.find((d) => d.is_today)?.date;
      if (!today || !cfg.timezone) {
        // Never guess the day from the browser clock — that is the bug V6-C5
        // went back and fixed in three places.
        toast.error(t("rowActionFailed"));
        return;
      }
      const next = (detail.actions ?? [])
        .filter((a) => a.status === "pending" && a.due_at)
        .sort(
          (x, y) =>
            new Date(x.due_at!).getTime() - new Date(y.due_at!).getTime() ||
            x.id.localeCompare(y.id),
        )[0];
      if (!next) {
        toast(t("rowNoAction"));
        return;
      }
      const dueDate = localDateOf(next.due_at!, cfg.timezone);
      const anchor = dueDate > today ? dueDate : today;
      await updateAction(
        next.id,
        { op: "snooze", snooze_days: 1, snooze_until: localMidnightUtc(addDays(anchor, 1), cfg.timezone) },
        token,
      );
      toast(t("rowRescheduled"));
      onMutated();
    } catch {
      toast.error(t("rowActionFailed"));
    } finally {
      setBusy(null);
    }
  }

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  return (
    // The row is a plain container with a click handler, and the TITLE is the
    // button — the shape PlanToday's ActionItem already uses. The row was
    // originally role="button" + tabIndex + its own Enter/Space handler, which
    // made it the keyboard target for everything inside it: keydown bubbles, so
    // a space typed in the inline note box hit the row's preventDefault (the
    // space never reached the input) and opened the application instead, and
    // tabbing to "Note" and pressing Enter fired the button AND the row. Making
    // the title the button removes the second code path rather than patching
    // it, and stops nesting interactive controls inside a role="button" whose
    // accessible name would otherwise swallow theirs.
    <div
      onClick={onOpen}
      className="group px-[var(--space-row-edge)] py-2.5 cursor-pointer transition-colors border-l-2 border-b"
      style={{
        borderLeftColor: isViewed ? "var(--primary)" : "transparent",
        borderBottomColor: "var(--border)",
        background: isViewed ? "var(--secondary)" : "transparent",
      }}
    >
      <div className="flex items-center gap-2.5">
        <button type="button" className="flex-1 min-w-0 text-left">
          <span className="block text-sm font-medium truncate group-hover:underline" style={{ color: "var(--ink-primary)" }}>
            {app.jobTitle}
          </span>
          <span className="block text-xs truncate mt-0.5" style={{ color: "var(--ink-muted)" }}>
            {app.company}
            <span className="mx-1">·</span>
            {subline}
          </span>
        </button>

        {/* Hover actions. focus-within keeps them reachable by keyboard, which
            display:none on hover alone would not. */}
        <div
          onClick={stop}
          className="shrink-0 hidden group-hover:flex group-focus-within:flex items-center gap-1"
        >
          <Button size="sm" variant="ghost" onClick={() => setNoting((v) => !v)} disabled={!!busy}>
            {t("rowNote")}
          </Button>
          {app.next_action_due_at && (
            <Button size="sm" variant="ghost" onClick={reschedule} loading={busy === "defer"}>
              {t("rowReschedule")}
            </Button>
          )}
        </div>

        <span
          className="shrink-0 px-1.5 py-0.5 rounded text-2xs font-semibold"
          style={{ background: style.bg, color: style.fg }}
        >
          {statusLabel}
        </span>
      </div>

      {noting && (
        <div onClick={stop} className="flex items-center gap-2 mt-2">
          <input
            autoFocus
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveNote();
              if (e.key === "Escape") { setNoting(false); setNote(""); }
            }}
            placeholder={t("logNotePlaceholder")}
            className="flex-1 min-w-0 h-8 px-2.5 rounded-md border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
            style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
          />
          <Button size="sm" variant="outline" onClick={saveNote} disabled={!note.trim()} loading={busy === "note"}>
            {t("logNote")}
          </Button>
        </div>
      )}
    </div>
  );
}
