"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import {
  listActions,
  getPlannerStats,
  getPlannerSettings,
  getPlannerWeek,
  getPlannerDay,
} from "@/api/client";
import type {
  ActionRead,
  PlannerStats,
  PlannerSettings,
  PlannerWeek,
  PlannerDayRead,
  PlannerDayLogRead,
} from "@/api/client";

// The list spans two weeks so upcoming deadlines stay visible; the daily cap is
// applied to a subset of it (see countsTowardToday in PlanToday).
const HORIZON_DAYS = 14;

/** The context sources a mutation can invalidate. The action list is not one of
 *  them on purpose: it has exactly two paths — a full `reload()`, or the
 *  optimistic removal in `mutateActions` — and adding a third way to refetch it
 *  is how the two get out of step. */
export type PlannerSource = "week" | "day";

export interface PlannerData {
  /** null until the first load finishes (or it failed — see `error`). */
  actions: ActionRead[] | null;
  /** Context sources. Each degrades to absent rather than failing the view. */
  stats: PlannerStats | null;
  settings: PlannerSettings | null;
  week: PlannerWeek | null;
  /** undefined = still loading. `day.log` null = no row today. */
  day: PlannerDayRead | undefined;
  /** The action list failed to load. Context failures do not set this. */
  error: boolean;
  reload: () => Promise<void>;
  refresh: (...sources: PlannerSource[]) => Promise<void>;
  mutateActions: (
    ids: string[],
    run: (token: string | null) => Promise<unknown>,
    invalidates: PlannerSource[],
  ) => Promise<void>;
  patchDayLog: (log: PlannerDayLogRead) => void;
}

/**
 * Every piece of state the Plan view reads, loaded once and invalidated by name.
 *
 * This replaces five `useState`s and three hand-rolled refresh functions living
 * in the component, where each mutation had to remember which ones it dirtied.
 * That shape has now been wrong twice in the same way — the week strip kept
 * showing dots for a to-do that had just been ticked (V3), the done bar sat at
 * its page-load value all day (V6) — and both times the bug was a caller that
 * updated the list and forgot the rest. Naming the sources moves that from
 * something each call site remembers to something it declares.
 *
 * The mockup's own architecture is a single store with one `renderToday()`;
 * this is the closest honest translation of it that keeps optimistic updates.
 */
export function usePlannerData(): PlannerData {
  const getToken = useApiToken();
  const [actions, setActions] = useState<ActionRead[] | null>(null);
  const [stats, setStats] = useState<PlannerStats | null>(null);
  const [settings, setSettings] = useState<PlannerSettings | null>(null);
  const [week, setWeek] = useState<PlannerWeek | null>(null);
  const [day, setDay] = useState<PlannerDayRead | undefined>(undefined);
  const [error, setError] = useState(false);
  // Ids whose removal is in flight. A reload that overlaps a mutation would
  // otherwise put a row the user just ticked back on the list.
  const removingRef = useRef<Set<string>>(new Set());

  const reload = useCallback(async () => {
    try {
      const token = await getToken();
      const horizon = new Date(Date.now() + HORIZON_DAYS * 86400_000).toISOString();
      // Only the list is allowed to fail the view. The rest is context: a strip
      // or a done bar that could not be fetched degrades to absent rather than
      // replacing today's work with an error page.
      const [res, st, cfg, wk, dayState] = await Promise.all([
        listActions({ due_on_or_before: horizon, include_undated: true }, token),
        getPlannerStats(undefined, token).catch(() => null),
        getPlannerSettings(token).catch(() => null),
        getPlannerWeek(undefined, token).catch(() => null),
        getPlannerDay(token).catch(() => undefined),
      ]);
      setActions(res.items.filter((a) => !removingRef.current.has(a.id)));
      setStats(st);
      setSettings(cfg);
      setWeek(wk);
      setDay(dayState);
      setError(false);
    } catch {
      setError(true);
    }
  }, [getToken]);

  useEffect(() => {
    reload();
  }, [reload]);

  /** Re-read the named sources. Each is independent: one failing neither blanks
   *  its own value nor stops the others, matching what the per-source refresh
   *  functions did before. */
  const refresh = useCallback(
    async (...sources: PlannerSource[]) => {
      await Promise.all(
        sources.map(async (source) => {
          try {
            const token = await getToken();
            if (source === "week") setWeek(await getPlannerWeek(undefined, token));
            else setDay(await getPlannerDay(token));
          } catch {
            // Keep the last good reading rather than blanking it: these are
            // context, and blank context reads as "nothing scheduled" / "nothing
            // done", which is a stronger claim than "could not load".
          }
        }),
      );
    },
    [getToken],
  );

  /**
   * Take rows off the list, run the mutation, then invalidate what it dirtied.
   *
   * The removal is optimistic and the failure path is a full reload — the list
   * must never be left claiming a to-do is open when the server disagrees, and
   * vice versa. `invalidates` is the part that used to be implicit: the strip's
   * per-day counts and the done bar are measured server-side (they fold in
   * overdue and undated work), so a caller that changes what is open or complete
   * has to say so.
   */
  const mutateActions = useCallback(
    async (
      ids: string[],
      run: (token: string | null) => Promise<unknown>,
      invalidates: PlannerSource[],
    ) => {
      ids.forEach((id) => removingRef.current.add(id));
      setActions((prev) => prev?.filter((a) => !ids.includes(a.id)) ?? null);
      try {
        const token = await getToken();
        await run(token);
        await refresh(...invalidates);
      } catch {
        // The rows have to come back — the mutation did not happen. Drop the
        // guard BEFORE reloading: reload() filters out every id still marked as
        // removing, so reloading first would discard exactly the rows it is
        // there to restore, and the list would keep claiming a to-do is done
        // until something else refetched it.
        //
        // This ordering used to be accidental. The pre-hook code fired its
        // reload without awaiting, so the synchronous `finally` cleared the
        // guard before the response landed; writing the await in without
        // moving the clear is what turns that accident into a silent bug.
        ids.forEach((id) => removingRef.current.delete(id));
        await reload();
      } finally {
        ids.forEach((id) => removingRef.current.delete(id));
      }
    },
    [getToken, refresh, reload],
  );

  /** Fold a freshly written day log into the cached day without a round trip.
   *  A no-op when the day has not loaded: `prev` being undefined means
   *  done_count/done_est are unknown, and inventing them would put numbers on
   *  the done bar that nothing measured. */
  const patchDayLog = useCallback((log: PlannerDayLogRead) => {
    setDay((prev) => (prev ? { ...prev, log } : prev));
  }, []);

  return { actions, stats, settings, week, day, error, reload, refresh, mutateActions, patchDayLog };
}
