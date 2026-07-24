import { getTranslations } from "next-intl/server";
import { ClipboardList } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { listApplications } from "@/api/client";
import type { ApplicationRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { TrackerShell } from "./TrackerShell";
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

  const list = await listApplications(
    { status_group: group, needs_action: needsAction, limit: FETCH_LIMIT },
    token,
  ).catch(() => ({ items: [] as ApplicationRead[], total: 0 }));

  const apps = list.items;

  // Truly-empty tracker (no applications at all, unfiltered) → full-width CTA.
  // A filtered-to-zero view falls through to the master-detail's own empty state.
  if (apps.length === 0 && !group && !needsAction) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <EmptyState
          icon={ClipboardList}
          title={t("emptyTitle")}
          action={
            <Link
              href="/jobs"
              className="inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
              style={{ color: "var(--primary)" }}
            >
              {t("goToJobs")}
            </Link>
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
        created_at: a.created_at,
        jobTitle: a.job?.title ?? "(untitled role)",
        company: a.job?.company ?? "",
      }))}
      group={group ?? "all"}
      needsAction={needsAction}
      totalCount={totalCount}
      currentPage={currentPage}
      totalPages={totalPages}
    />
  );
}
