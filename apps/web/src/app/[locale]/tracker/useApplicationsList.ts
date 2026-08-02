"use client";

import { useCallback, useEffect, useState } from "react";

import { listApplications } from "@/api/client";
import type { ApplicationRead } from "@/api/client";
import { useApiToken } from "@/hooks/useApiToken";

/** Applications grouped the way the sidebar shows them. */
export interface ApplicationGroups {
  /** Live: applied through interviewing. The work that can still go somewhere. */
  active: ApplicationRead[];
  /** Not applied yet — the queue, ordered by the queue's own ranking. */
  planned: ApplicationRead[];
  /** Rejected / withdrawn / ghosted. Collapsed by default. */
  closed: ApplicationRead[];
}

export interface ApplicationsList extends ApplicationGroups {
  /** null until the first load finishes. */
  loaded: boolean;
  error: boolean;
  reload: () => Promise<void>;
}

const EMPTY: ApplicationGroups = { active: [], planned: [], closed: [] };

/**
 * Every application the sidebar renders, in one place.
 *
 * Three requests rather than one unfiltered page: the server already groups by
 * status and each group has its own page size, so asking for "all" and
 * splitting client-side would either truncate the long tail of closed rows or
 * pull the whole history to show three of them.
 *
 * `include_fit` is asked for on the planned group only. Fit drives that group's
 * ranking; for anything already applied the number is history, and the flag
 * costs a per-row lookup.
 *
 * Deliberately NOT part of usePlannerData: that store is the day's measured
 * numbers, invalidated by name after each mutation. This is a list of records,
 * refetched wholesale, and folding it in would put a second meaning on every
 * `refresh(...)` call site.
 */
export function useApplicationsList(): ApplicationsList {
  const getToken = useApiToken();
  const [groups, setGroups] = useState<ApplicationGroups>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  const reload = useCallback(async () => {
    try {
      const token = await getToken();
      const [active, planned, closed] = await Promise.all([
        listApplications({ status_group: "active", limit: 100 }, token),
        listApplications({ status_group: "planned", include_fit: true, limit: 100 }, token),
        listApplications({ status_group: "closed", limit: 100 }, token),
      ]);
      setGroups({ active: active.items, planned: planned.items, closed: closed.items });
      setLoaded(true);
      setError(false);
    } catch {
      setError(true);
      setLoaded(true);
    }
  }, [getToken]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { ...groups, loaded, error, reload };
}

/**
 * Case-insensitive match on company and role.
 *
 * Client-side on purpose for now: the list endpoint has no search parameter,
 * and the alternative — adding one — is its own change with its own tests. With
 * the groups capped at 100 rows each this filters what is already on screen,
 * which is what a job seeker's own pipeline realistically is. A workspace that
 * outgrows that needs the server-side version, not a bigger limit.
 */
export function matchesQuery(a: ApplicationRead, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const company = a.job?.company?.toLowerCase() ?? "";
  const title = a.job?.title?.toLowerCase() ?? "";
  return company.includes(q) || title.includes(q);
}
