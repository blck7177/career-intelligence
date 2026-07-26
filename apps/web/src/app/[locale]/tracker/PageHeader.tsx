"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { getPlannerSettings } from "@/api/client";

/** Tracker page header (mockup .pagehead): "Tracker" + today's date + "Week N of
 *  search". Date/week are computed client-side (in an effect, to avoid an SSR
 *  hydration mismatch); Week N reads settings.search_started_at. */
export function PageHeader() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [meta, setMeta] = useState<{ date: string; week: number | null } | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const date = new Date().toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
      let week: number | null = null;
      try {
        const s = await getPlannerSettings(await getToken());
        if (s.search_started_at) {
          const start = new Date(s.search_started_at + "T00:00:00");
          if (!isNaN(start.getTime())) {
            const days = Math.floor((Date.now() - start.getTime()) / 86400_000);
            if (days >= 0) week = Math.floor(days / 7) + 1;
          }
        }
      } catch { /* keep date-only */ }
      if (alive) setMeta({ date, week });
    })();
    return () => { alive = false; };
  }, [getToken]);

  return (
    <div className="shrink-0 flex items-baseline gap-3 px-[var(--space-row-edge)] pt-4 pb-1">
      <h1 className="text-lg font-semibold leading-none" style={{ color: "var(--ink-primary)" }}>{t("pageTitle")}</h1>
      {meta && (
        <span className="ml-auto text-2xs" style={{ color: "var(--ink-faint)" }}>
          {meta.date}
          {meta.week !== null && <> · {t("settingsWeekOfSearch", { n: meta.week })}</>}
        </span>
      )}
    </div>
  );
}
