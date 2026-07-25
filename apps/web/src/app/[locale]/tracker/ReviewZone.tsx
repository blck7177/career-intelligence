"use client";

import { useTranslations } from "next-intl";

/** Plan · Review zone. Placeholder until Wave 5 (the LLM weekly review) ships;
 *  lights up when planner_reviews data exists. */
export function ReviewZone() {
  const t = useTranslations("tracker");
  return (
    <section className="w-full">
      <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--ink-primary)" }}>{t("zoneReview")}</h2>
      <div className="rounded-lg border border-dashed p-4 text-center" style={{ borderColor: "var(--border)" }}>
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>{t("reviewSoon")}</p>
        <p className="text-2xs mt-1" style={{ color: "var(--ink-faint)" }}>{t("reviewSoonSub")}</p>
      </div>
    </section>
  );
}
