import { getTranslations } from "next-intl/server";
import { ClipboardList } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { listApplications, getApplicationsSummary } from "@/api/client";
import type { ApplicationRead } from "@/api/client";
import type { AppCounts } from "./ApplicationsMasterDetail";
import { getServerToken } from "@/lib/server-auth";
import { TrackerShell } from "./TrackerShell";
import { TrackerEmptyAdd } from "./TrackerEmptyAdd";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";

// Backend caps limit at 500; paging is done client-side over this batch.
const FETCH_LIMIT = 500;
const PAGE_SIZE = 20;

interface PageProps {
  searchParams: Promise<{
    group?: string; // planned | active | closed  (absent = all)
    needs_action?: string;
    selected?: string;
    page?: string;
  }>;
}

export default async function TrackerPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const token = await getServerToken();
  const t = await getTranslations("tracker");

  const group = params.group;
  const needsAction = params.needs_action === "1";

  // List (current filter) + summary (workspace-wide per-group counts for the
  // filter pills) fetched concurrently. Summary failure degrades gracefully to
  // pills without counts.
  const [list, summary] = await Promise.all([
    listApplications(
      { status_group: group, needs_action: needsAction, limit: FETCH_LIMIT },
      token,
    ).catch(() => ({ items: [] as ApplicationRead[], total: 0 })),
    getApplicationsSummary(token).catch(() => null),
  ]);

  const apps = list.items;

  let counts: AppCounts | null = null;
  if (summary) {
    const all = Object.values(summary.by_status).reduce((a, b) => a + b, 0);
    counts = {
      all,
      active: summary.active,
      planned: summary.planned,
      closed: all - summary.active - summary.planned,
      needsAction: summary.needs_action,
    };
  }

  // Truly-empty tracker (no applications at all, unfiltered) → full-width CTA.
  // A filtered-to-zero view falls through to the master-detail's own empty state.
  if (apps.length === 0 && !group && !needsAction) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <EmptyState
          icon={ClipboardList}
          title={t("emptyTitle")}
          action={
            <div className="flex flex-col items-center gap-3">
              <TrackerEmptyAdd />
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

  const totalCount = apps.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, Number(params.page) || 1), totalPages);
  const paged = apps.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  return (
    <TrackerShell
      applications={paged.map((a) => ({
        id: a.id,
        status: a.status,
        lane: a.lane ?? null,
        excitement: a.excitement ?? null,
        applied_at: a.applied_at ?? null,
        next_action_due_at: a.next_action_due_at ?? null,
        next_action_type: a.next_action_type ?? null,
        created_at: a.created_at,
        jobTitle: a.job?.title ?? "(untitled role)",
        company: a.job?.company ?? "",
      }))}
      group={group ?? "all"}
      needsAction={needsAction}
      totalCount={totalCount}
      currentPage={currentPage}
      totalPages={totalPages}
      counts={counts}
    />
  );
}
