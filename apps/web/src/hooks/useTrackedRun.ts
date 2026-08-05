"use client";

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import { getRun } from "@/api/client";
import {
  onRunSettled,
  peekTracked,
  subscribeTracked,
  type RunFetcher,
  type SettledRun,
  type TrackedRun,
} from "@/lib/runTracker";
import { useApiToken, useApiUserId } from "@/hooks/useApiToken";

/**
 * React's view of the run tracker. The store itself (lib/runTracker) holds no
 * React and no API client, which is what lets it outlive the components here.
 */

/** Sentinel owner for when nobody is signed in. In a deployed app that state
 *  never reaches these buttons — middleware protects every route — but it is
 *  the standing state under DEV_AUTH_BYPASS, where Clerk has no session and
 *  useApiUserId answers null. Keying on a raw null there would leave every
 *  tracked run invisible, i.e. the feature dead exactly where it is exercised
 *  most. Entries under this key are only ever visible to a signed-out page, so
 *  it cannot show one account's run to another. */
const ANONYMOUS_OWNER = "anonymous";

/** Who tracked runs belong to. Always a string, so callers never have to decide
 *  what to do about a half-resolved session. */
export function useRunOwnerId(): string {
  return useApiUserId() ?? ANONYMOUS_OWNER;
}

/** The run occupying this slot, or null. Re-renders when that changes, whoever
 *  started the run and whenever — including a run started before this component
 *  was ever mounted. */
export function useTrackedRun(key: string | null, userId: string | null): TrackedRun | null {
  const snapshot = useCallback(() => peekTracked(key, userId), [key, userId]);
  return useSyncExternalStore(subscribeTracked, snapshot, () => null);
}

/** Runs the handler when a run in this slot ends — once, only while mounted.
 *  Whoever is on screen uses it to refresh; nobody being on screen is fine,
 *  because a component that mounts later fetches current data anyway. */
export function useRunSettled(key: string | null, handler: (run: SettledRun) => void): void {
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => {
    if (!key) return;
    return onRunSettled((run) => {
      if (run.key === key) latest.current(run);
    });
  }, [key]);
}

/** Bridges the store to the API client: the store is handed a way to read a
 *  run's status rather than importing one. */
export function useRunFetcher(): RunFetcher {
  const getToken = useApiToken();
  return useCallback(async (runId: string) => getRun(runId, await getToken()), [getToken]);
}
