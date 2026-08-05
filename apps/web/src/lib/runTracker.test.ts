import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearTracking,
  onRunSettled,
  peekTracked,
  rehydrateTracking,
  runKey,
  startTracking,
  subscribeTracked,
  type RunFetcher,
  type RunStatusSnapshot,
  type SettledRun,
} from "./runTracker";

const USER = "user_abc";
const OTHER_USER = "user_xyz";
const KEY = runKey("job_report", "job_1");

/** Tiny interval + real timers: the store's scheduling is what is under test,
 *  so faking it away would test very little. */
const FAST = { intervalMs: 1, timeoutMs: 5_000 };

function tick(ms = 25): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** sessionStorage does not exist in the node test environment; the store treats
 *  that as "no persistence" and carries on, so tests that care install this. */
function installStorage(): Map<string, string> {
  const backing = new Map<string, string>();
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    value: {
      getItem: (k: string) => backing.get(k) ?? null,
      setItem: (k: string, v: string) => void backing.set(k, v),
      removeItem: (k: string) => void backing.delete(k),
    },
  });
  return backing;
}

function removeStorage(): void {
  Reflect.deleteProperty(globalThis as object, "sessionStorage");
}

const unsubscribers: Array<() => void> = [];

function collectSettled(): SettledRun[] {
  const seen: SettledRun[] = [];
  unsubscribers.push(onRunSettled((run) => seen.push(run)));
  return seen;
}

/** Answers with each status in turn, then repeats the last one forever. */
function fetcherReturning(...statuses: RunStatusSnapshot[]): RunFetcher {
  const queue = [...statuses];
  return async () => (queue.length > 1 ? (queue.shift() as RunStatusSnapshot) : queue[0]);
}

beforeEach(() => {
  clearTracking();
});

afterEach(() => {
  while (unsubscribers.length) unsubscribers.pop()!();
  clearTracking();
  removeStorage();
});

describe("startTracking", () => {
  it("keeps the run visible while it is still running", async () => {
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );

    expect(peekTracked(KEY, USER)?.runId).toBe("run_1");
    await tick();
    // Several poll rounds later it is still tracked — this is the thing the old
    // in-component polling could not do once the component unmounted.
    expect(peekTracked(KEY, USER)?.runId).toBe("run_1");
  });

  it("returns a stable object identity so it is safe as a store snapshot", () => {
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );
    expect(peekTracked(KEY, USER)).toBe(peekTracked(KEY, USER));
  });

  it("hides another account's run", () => {
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: OTHER_USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );
    expect(peekTracked(KEY, USER)).toBeNull();
    expect(peekTracked(KEY, OTHER_USER)).not.toBeNull();
  });

  it("reports nothing when the user is not resolved yet", () => {
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );
    expect(peekTracked(KEY, null)).toBeNull();
  });

  it("notifies snapshot subscribers when a run starts and when it ends", async () => {
    const notified = vi.fn();
    unsubscribers.push(subscribeTracked(notified));

    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "succeeded" }),
      FAST,
    );
    expect(notified).toHaveBeenCalledTimes(1);

    await tick();
    expect(notified).toHaveBeenCalledTimes(2);
  });
});

describe("settling", () => {
  it("announces success once and stops tracking", async () => {
    const settled = collectSettled();
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }, { status: "succeeded" }),
      FAST,
    );

    await tick();
    expect(settled).toHaveLength(1);
    expect(settled[0]).toMatchObject({ key: KEY, runId: "run_1", runType: "job_report", status: "succeeded" });
    expect(peekTracked(KEY, USER)).toBeNull();

    // Polling really stopped — no second announcement however long we wait.
    await tick();
    expect(settled).toHaveLength(1);
  });

  it("carries the server's message through on failure", async () => {
    const settled = collectSettled();
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "failed", error_message: "model refused" }),
      FAST,
    );

    await tick();
    expect(settled[0]).toMatchObject({ status: "failed", errorMessage: "model refused" });
  });

  it("treats needs_review and cancelled as ends, not as still-running", async () => {
    for (const status of ["needs_review", "cancelled"]) {
      clearTracking();
      const settled = collectSettled();
      startTracking(
        { key: KEY, runId: `run_${status}`, runType: "job_report", userId: USER },
        fetcherReturning({ status }),
        FAST,
      );
      await tick();
      expect(settled.at(-1)).toMatchObject({ status });
      expect(peekTracked(KEY, USER)).toBeNull();
    }
  });

  it("gives up after the timeout instead of spinning forever", async () => {
    const settled = collectSettled();
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      { intervalMs: 1, timeoutMs: 5, startedAt: Date.now() - 1000 },
    );

    await tick();
    expect(settled[0]).toMatchObject({ status: "timed_out", errorMessage: null });
    expect(peekTracked(KEY, USER)).toBeNull();
  });
});

describe("fetch failures", () => {
  it("keeps polling through a transient error", async () => {
    const settled = collectSettled();
    let calls = 0;
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      async () => {
        calls += 1;
        if (calls === 1) throw Object.assign(new Error("boom"), { status: 500 });
        return { status: "succeeded" };
      },
      FAST,
    );

    await tick();
    expect(calls).toBeGreaterThan(1);
    expect(settled).toHaveLength(1);
    expect(settled[0].status).toBe("succeeded");
  });

  it("drops a run that is gone or not ours, without announcing an end", async () => {
    const settled = collectSettled();
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      async () => {
        throw Object.assign(new Error("not found"), { status: 404 });
      },
      FAST,
    );

    await tick();
    expect(peekTracked(KEY, USER)).toBeNull();
    // No toast for a run we simply lost sight of — we do not know how it ended.
    expect(settled).toHaveLength(0);
  });
});

describe("rehydrateTracking", () => {
  beforeEach(() => {
    installStorage();
  });

  it("picks a run back up after a reload", async () => {
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );
    // Simulate the reload: memory is gone, sessionStorage is not.
    clearTracking();
    expect(peekTracked(KEY, USER)).toBeNull();

    // sessionStorage was rewritten by clearTracking, so re-seed it the way a
    // real reload would have found it.
    (globalThis.sessionStorage as Storage).setItem(
      "career.runTracker.v1",
      JSON.stringify([
        { key: KEY, runId: "run_1", runType: "job_report", userId: USER, startedAt: Date.now(), intervalMs: 1, timeoutMs: 5000 },
      ]),
    );

    const restored = rehydrateTracking(USER, fetcherReturning({ status: "running" }), FAST);
    expect(restored).toBe(1);
    expect(peekTracked(KEY, USER)?.runId).toBe("run_1");
  });

  it("leaves another account's run alone", () => {
    (globalThis.sessionStorage as Storage).setItem(
      "career.runTracker.v1",
      JSON.stringify([
        { key: KEY, runId: "run_1", runType: "job_report", userId: OTHER_USER, startedAt: Date.now(), intervalMs: 1, timeoutMs: 5000 },
      ]),
    );

    expect(rehydrateTracking(USER, fetcherReturning({ status: "running" }), FAST)).toBe(0);
    expect(peekTracked(KEY, USER)).toBeNull();
    expect(peekTracked(KEY, OTHER_USER)).toBeNull();
  });

  it("drops an entry that is already past its timeout", () => {
    (globalThis.sessionStorage as Storage).setItem(
      "career.runTracker.v1",
      JSON.stringify([
        { key: KEY, runId: "run_old", runType: "job_report", userId: USER, startedAt: Date.now() - 60_000, intervalMs: 1, timeoutMs: 1000 },
      ]),
    );

    expect(rehydrateTracking(USER, fetcherReturning({ status: "running" }))).toBe(0);
    expect(peekTracked(KEY, USER)).toBeNull();
  });

  it("survives junk in storage", () => {
    (globalThis.sessionStorage as Storage).setItem("career.runTracker.v1", "{not json");
    expect(rehydrateTracking(USER, fetcherReturning({ status: "running" }))).toBe(0);
  });

  it("does not double-track a run already in memory", () => {
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );
    expect(rehydrateTracking(USER, fetcherReturning({ status: "running" }), FAST)).toBe(0);
    expect(peekTracked(KEY, USER)?.runId).toBe("run_1");
  });
});

describe("without sessionStorage", () => {
  it("tracks in memory and reports nothing to restore", async () => {
    removeStorage();
    startTracking(
      { key: KEY, runId: "run_1", runType: "job_report", userId: USER },
      fetcherReturning({ status: "running" }),
      FAST,
    );
    expect(peekTracked(KEY, USER)?.runId).toBe("run_1");
    expect(rehydrateTracking(USER, fetcherReturning({ status: "running" }))).toBe(0);
  });
});
