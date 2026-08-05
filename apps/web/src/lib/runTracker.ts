/**
 * In-flight runs, tracked outside the React tree.
 *
 * A run takes minutes; the button that starts one takes a click. Those two do
 * not share a lifetime, but every generate button in this app kept its polling
 * in component state anyway — so switching tabs, closing the peek, or opening
 * the job modal over it abandoned a run that was still executing server-side.
 * You came back to a button that looked untouched, and nothing ever said the
 * work had finished.
 *
 * Polling therefore lives here, in module scope, and components subscribe to it.
 * Two channels, deliberately separate:
 *   - the snapshot (peekTracked/subscribeTracked) answers "is this slot busy
 *     right now", which is what a button needs on mount however long after the
 *     click that is;
 *   - onRunSettled fires once per run, for the things that must happen exactly
 *     once — the toast, and a data refresh for whoever is on screen.
 *
 * Every entry is keyed by user id. Clerk routes a sign-out through the Next
 * router rather than reloading the page, so this module outlives an account
 * switch (see useApiUserId) and an unkeyed entry would show one person's run to
 * the next one.
 *
 * The run fetcher is passed in rather than imported so this file stays free of
 * runtime `@/` imports — vitest has no alias config here, which is why the
 * existing tests only ever import from `@/` with `import type`.
 */

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "needs_review"]);

const DEFAULT_INTERVAL_MS = 3000;
/** Matches the old in-component pollRunUntilDone default, so moving the poll
 *  out of the component does not quietly change how long a run is watched. */
const DEFAULT_TIMEOUT_MS = 600_000;

const STORAGE_KEY = "career.runTracker.v1";

/** The part of RunRead this module reads. Declared structurally rather than
 *  imported so the store has no dependency on the API client. */
export interface RunStatusSnapshot {
  status: string;
  error_message?: string | null;
}

export type RunFetcher = (runId: string) => Promise<RunStatusSnapshot>;

export interface TrackedRun {
  key: string;
  runId: string;
  runType: string;
  userId: string;
  startedAt: number;
}

export interface SettledRun {
  key: string;
  runId: string;
  runType: string;
  userId: string;
  /** A run status, or "timed_out" when we stopped watching before the server
   *  reached one. Never "running"/"queued". */
  status: string;
  errorMessage: string | null;
}

interface Entry extends TrackedRun {
  intervalMs: number;
  timeoutMs: number;
}

/** One run per subject per type — the same pair the backend's
 *  uq_active_agent_run_per_workspace_type constraint allows to be active. */
export function runKey(runType: string, subjectId: string): string {
  return `${runType}:${subjectId}`;
}

const running = new Map<string, Entry>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const snapshotListeners = new Set<() => void>();
const settledListeners = new Set<(run: SettledRun) => void>();

let fetcher: RunFetcher | null = null;

function emit(): void {
  for (const listener of [...snapshotListeners]) listener();
}

function persist(): void {
  try {
    if (typeof sessionStorage === "undefined") return;
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...running.values()]));
  } catch {
    // Private mode, quota, disabled storage — surviving a reload is a bonus,
    // not the feature. In-memory tracking carries on either way.
  }
}

function clearTimer(key: string): void {
  const timer = timers.get(key);
  if (timer !== undefined) {
    clearTimeout(timer);
    timers.delete(key);
  }
}

function schedule(entry: Entry): void {
  clearTimer(entry.key);
  timers.set(
    entry.key,
    setTimeout(() => {
      void poll(entry.key);
    }, entry.intervalMs),
  );
}

function forget(key: string): void {
  clearTimer(key);
  running.delete(key);
  persist();
  emit();
}

function settle(entry: Entry, status: string, errorMessage: string | null): void {
  forget(entry.key);
  const payload: SettledRun = {
    key: entry.key,
    runId: entry.runId,
    runType: entry.runType,
    userId: entry.userId,
    status,
    errorMessage,
  };
  for (const listener of [...settledListeners]) listener(payload);
}

async function poll(key: string): Promise<void> {
  const entry = running.get(key);
  if (!entry) return;

  if (Date.now() - entry.startedAt > entry.timeoutMs) {
    settle(entry, "timed_out", null);
    return;
  }

  const fetchRun = fetcher;
  if (!fetchRun) {
    schedule(entry);
    return;
  }

  let snapshot: RunStatusSnapshot;
  try {
    snapshot = await fetchRun(entry.runId);
  } catch (err) {
    const status = (err as { status?: number } | null)?.status;
    // Gone, or not ours to watch: stop without announcing anything. Every other
    // failure (offline, 5xx, a blip) is treated as transient and retried — the
    // timeout above is the backstop that keeps a spinner from living forever.
    if (status === 401 || status === 403 || status === 404) {
      forget(key);
      return;
    }
    if (running.has(key)) schedule(entry);
    return;
  }

  // Dropped or replaced while the request was in flight.
  if (running.get(key) !== entry) return;

  if (TERMINAL.has(snapshot.status)) {
    settle(entry, snapshot.status, snapshot.error_message ?? null);
    return;
  }
  schedule(entry);
}

export interface TrackOptions {
  intervalMs?: number;
  timeoutMs?: number;
  startedAt?: number;
  /** Check once right away instead of waiting out the first interval. Used when
   *  restoring after a reload, where the run may already be done. */
  immediate?: boolean;
}

export function startTracking(
  init: { key: string; runId: string; runType: string; userId: string },
  fetchRun: RunFetcher,
  options: TrackOptions = {},
): void {
  fetcher = fetchRun;
  const entry: Entry = {
    ...init,
    startedAt: options.startedAt ?? Date.now(),
    intervalMs: options.intervalMs ?? DEFAULT_INTERVAL_MS,
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  };
  clearTimer(entry.key);
  running.set(entry.key, entry);
  persist();
  emit();
  if (options.immediate) {
    void poll(entry.key);
  } else {
    schedule(entry);
  }
}

/** The tracked run in this slot, or null. Returns the same object identity while
 *  nothing changes, so it is safe as a useSyncExternalStore snapshot. */
export function peekTracked(key: string | null, userId: string | null): TrackedRun | null {
  if (!key || !userId) return null;
  const entry = running.get(key);
  if (!entry || entry.userId !== userId) return null;
  return entry;
}

export function subscribeTracked(listener: () => void): () => void {
  snapshotListeners.add(listener);
  return () => {
    snapshotListeners.delete(listener);
  };
}

export function onRunSettled(listener: (run: SettledRun) => void): () => void {
  settledListeners.add(listener);
  return () => {
    settledListeners.delete(listener);
  };
}

/** Restore runs this user started before a reload. Returns how many were picked
 *  back up. Entries belonging to another account, or already past their
 *  timeout, are left behind. */
export function rehydrateTracking(
  userId: string,
  fetchRun: RunFetcher,
  options: Pick<TrackOptions, "intervalMs" | "timeoutMs"> = {},
): number {
  fetcher = fetchRun;
  let stored: unknown;
  try {
    if (typeof sessionStorage === "undefined") return 0;
    stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
  } catch {
    return 0;
  }
  if (!Array.isArray(stored)) return 0;

  let restored = 0;
  for (const raw of stored) {
    const saved = raw as Partial<Entry> | null;
    if (!saved?.key || !saved.runId || !saved.runType) continue;
    if (saved.userId !== userId) continue;
    if (running.has(saved.key)) continue;
    const startedAt = typeof saved.startedAt === "number" ? saved.startedAt : 0;
    const timeoutMs = options.timeoutMs ?? saved.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    if (Date.now() - startedAt > timeoutMs) continue;
    running.set(saved.key, {
      key: saved.key,
      runId: saved.runId,
      runType: saved.runType,
      userId,
      startedAt,
      intervalMs: options.intervalMs ?? saved.intervalMs ?? DEFAULT_INTERVAL_MS,
      timeoutMs,
    });
    restored += 1;
    void poll(saved.key);
  }
  if (restored > 0) {
    persist();
    emit();
  }
  return restored;
}

/** Drop everything, e.g. on sign-out. Listeners are left registered — they
 *  belong to mounted components, which manage their own subscriptions. */
export function clearTracking(): void {
  for (const key of [...running.keys()]) clearTimer(key);
  running.clear();
  persist();
  emit();
}
