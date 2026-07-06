"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Eases a displayed number from its previous value up to `target` whenever
 * `target` changes. Pass `initial` to animate up on first mount too (e.g. a
 * score reveal); omit it and the first render shows `target` immediately,
 * only animating on later changes (e.g. a nav badge count refetch) so the
 * number doesn't visibly tick on every route change.
 *
 * Skips the tween entirely under prefers-reduced-motion.
 */
export function useCountUp(target: number, opts?: { durationMs?: number; initial?: number }): number {
  const durationMs = opts?.durationMs ?? 700;
  const [value, setValue] = useState(opts?.initial ?? target);
  const fromRef = useRef(opts?.initial ?? target);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;

    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      fromRef.current = target;
      setValue(target);
      return;
    }

    const start = performance.now();
    let raf: number;

    function tick(now: number) {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(from + (target - from) * eased));
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return value;
}
