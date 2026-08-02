import { listApplications } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { TrackerShell } from "./TrackerShell";

export const dynamic = "force-dynamic";

/**
 * The tracker page fetches one thing: whether this workspace has tracked
 * anything at all, which decides between the first-run invitation and the
 * planner.
 *
 * It used to fetch 500 applications here and page through them client-side, to
 * fill the Applications sub-view. The sidebar that replaced it loads its own
 * groups in the browser and re-reads them after every mutation, so serving that
 * list from here as well would only guarantee two readings of it.
 *
 * One row, unfiltered, is the whole question: no status_group means every
 * status, so a workspace whose applications are all rejected still gets the
 * planner rather than being told it has nothing. The summary endpoint would
 * also answer it, but it materialises up to a thousand action-joined rows to
 * compute a needs_action count this page never reads.
 */
export default async function TrackerPage() {
  const token = await getServerToken();
  const probe = await listApplications({ limit: 1 }, token).catch(() => null);

  // A failed probe renders the planner, not the invitation: telling someone
  // with fifty applications that they have none is the worse of the two ways to
  // be wrong, and the sidebar reports its own load failure in place.
  const empty = probe ? probe.items.length === 0 : false;

  return <TrackerShell empty={empty} />;
}
