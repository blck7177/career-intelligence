"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { getPlannerSettings } from "@/api/client";
import { PageHeader as SharedPageHeader } from "@/components/ui/page-header";

/** Tracker's page header: the shared ui/PageHeader plus this tab's own meta
 *  stamp ("Fri, Jul 25 · Week 3 of search").
 *
 *  The date/week computation stays here, in an effect, on purpose: it reads the
 *  *client's* local date, so computing it during a server render would both
 *  cause a hydration mismatch and show the server's timezone. Everything
 *  data-shaped reaches the shared component as an already-rendered string. */
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
    <SharedPageHeader
      title={t("pageTitle")}
      gutter="edge"
      meta={
        meta
          ? `${meta.date}${meta.week !== null ? ` · ${t("settingsWeekOfSearch", { n: meta.week })}` : ""}`
          : undefined
      }
    />
  );
}
