"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { fmtTs } from "@/lib/utils";
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
        <ApplicationDetailPane applicationId={selectedForPane} onListChanged={() => router.refresh()} />
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
}

function AppListRow({ app, isViewed, statusLabel, subline, onOpen }: RowProps) {
  const style = STATUS_STYLE[app.status] ?? STATUS_STYLE.planned;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className="group flex items-center gap-2.5 px-[var(--space-row-edge)] py-2.5 cursor-pointer transition-colors border-l-2 border-b"
      style={{
        borderLeftColor: isViewed ? "var(--primary)" : "transparent",
        borderBottomColor: "var(--border)",
        background: isViewed ? "var(--secondary)" : "transparent",
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate group-hover:underline" style={{ color: "var(--ink-primary)" }}>
          {app.jobTitle}
        </div>
        <div className="text-xs truncate mt-0.5" style={{ color: "var(--ink-muted)" }}>
          {app.company}
          <span className="mx-1">·</span>
          {subline}
        </div>
      </div>
      <span
        className="shrink-0 px-1.5 py-0.5 rounded text-2xs font-semibold"
        style={{ background: style.bg, color: style.fg }}
      >
        {statusLabel}
      </span>
    </div>
  );
}
