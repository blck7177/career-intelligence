import { getTranslations } from "next-intl/server";
import { ChevronLeft } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { ApplicationDetailPane } from "../ApplicationDetailPane";

export const dynamic = "force-dynamic";

/** Mobile full-page detail view. On desktop the pane renders inline in the
 *  master-detail; on phones openRow() navigates here instead. */
export default async function TrackerDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("tracker");
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="shrink-0 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
        <Link
          href="/tracker"
          className="inline-flex items-center gap-1 text-sm font-medium"
          style={{ color: "var(--primary)" }}
        >
          <ChevronLeft size={16} />
          {t("title")}
        </Link>
      </div>
      <ApplicationDetailPane applicationId={id} />
    </div>
  );
}
