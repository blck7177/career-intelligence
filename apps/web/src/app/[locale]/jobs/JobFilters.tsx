"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { SlidersHorizontal, ChevronDown, X } from "lucide-react";
import { Collapsible } from "@/components/Collapsible";
import { Select } from "@/components/ui/select";

interface ProfileOption {
  id: string;
  label: string;
}

interface JobFiltersProps {
  profiles: ProfileOption[];
  roleCategories: string[];
  companies: string[];
}

const SORT_LABEL_KEY: Record<string, string> = {
  newest: "sortNewest",
  oldest: "sortOldest",
  company: "sortCompany",
  fit: "sortFit",
};

const SENIORITY_LABEL_KEY: Record<string, string> = {
  junior: "seniorityJunior",
  mid: "seniorityMid",
  senior: "senioritySenior",
  lead: "seniorityLead",
  director: "seniorityDirector",
};

const CONFIDENCE_LABEL_KEY: Record<string, string> = {
  high: "confidenceHigh",
  medium: "confidenceMedium",
  low: "confidenceLow",
};

export function JobFilters({ profiles, roleCategories, companies }: JobFiltersProps) {
  const t = useTranslations("jobFilters");
  const router = useRouter();
  const sp = useSearchParams();
  const [panelOpen, setPanelOpen] = useState(false);

  const update = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(sp.toString());
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      params.delete("page");
      // Changing the filter set rebuilds the list, so any selected-row anchor
      // from the old list no longer applies — drop it (the master-detail
      // re-selects the first row of the new results).
      params.delete("selected");
      router.push(`/jobs?${params.toString()}`);
    },
    [router, sp],
  );

  const profileId = sp.get("profile_id") ?? "";
  const roleCategory = sp.get("role_category") ?? "";
  const seniority = sp.get("seniority") ?? "";
  const confidence = sp.get("confidence") ?? "";
  const company = sp.get("company") ?? "";
  const rawSort = sp.get("sort") ?? "";
  // page.tsx defaults to fit-sort when a profile is active and no sort was
  // chosen. Mirror that here so the dropdown/chip never silently disagree
  // with what's actually on screen.
  const effectiveSort = rawSort || (profileId ? "fit" : "newest");

  useEffect(() => {
    if (!profileId && profiles.length === 1) {
      update("profile_id", profiles[0].id);
    }
  }, [profileId, profiles, update]);

  const activeProfile = profiles.find((p) => p.id === profileId);

  // Active facets surface as removable chips next to the trigger — so the
  // current state of the list is always visible without opening the panel,
  // instead of five permanently-open dropdown rows fighting for attention.
  const chips: { key: string; label: string; onRemove: () => void }[] = [];
  if (effectiveSort !== "newest") {
    chips.push({
      key: "sort",
      label: `${t("sort")} ${t(SORT_LABEL_KEY[effectiveSort])}`,
      // Clearing the fit default while a profile is still active would just
      // fall back to fit again, so send it to "newest" explicitly instead.
      onRemove: () => update("sort", effectiveSort === "fit" ? "newest" : null),
    });
  }
  if (profileId && activeProfile) {
    chips.push({ key: "profile", label: `${t("fitFor")} ${activeProfile.label}`, onRemove: () => update("profile_id", null) });
  }
  if (company) {
    chips.push({ key: "company", label: `${t("company")} ${company}`, onRemove: () => update("company", null) });
  }
  if (roleCategory) {
    chips.push({ key: "role", label: `${t("roleCategory")} ${roleCategory.split(" / ")[0]}`, onRemove: () => update("role_category", null) });
  }
  if (seniority) {
    chips.push({ key: "seniority", label: `${t("seniority")} ${t(SENIORITY_LABEL_KEY[seniority] ?? "all")}`, onRemove: () => update("seniority", null) });
  }
  if (confidence) {
    chips.push({ key: "confidence", label: `${t("confidence")} ${t(CONFIDENCE_LABEL_KEY[confidence] ?? "all")}`, onRemove: () => update("confidence", null) });
  }

  const labelClass = "text-2xs font-medium text-[var(--ink-muted)]";

  return (
    <div className="flex flex-col gap-2 rounded-lg p-2" style={{ background: "var(--muted)" }}>
      {/* Active-filter chips read left-to-right first (the current state);
          the Filters trigger and Clear filters travel together as one
          "manage the filter set" pair, anchored to the row's trailing edge
          via ml-auto — so they land bottom-right on whichever wrapped line
          they end up on, instead of competing with the chips for the same
          shape/weight up front. */}
      <div className="flex flex-wrap items-center gap-2">
        {chips.map((chip) => (
          <span
            key={chip.key}
            className="inline-flex items-center gap-1.5 h-[26px] pl-2.5 pr-1 rounded-md text-xs font-medium max-w-[168px] shrink-0"
            style={{ background: "var(--secondary)", color: "var(--secondary-foreground)" }}
          >
            <span className="truncate min-w-0">{chip.label}</span>
            <button
              type="button"
              onClick={chip.onRemove}
              aria-label={t("clearFilters")}
              className="flex items-center justify-center w-[15px] h-[15px] rounded-full hover:bg-black/10 transition-colors shrink-0"
            >
              <X size={10} />
            </button>
          </span>
        ))}

        <div className="flex items-center gap-2.5 ml-auto shrink-0">
          {/* Ghost button + rotating chevron — reads as a disclosure control
              instead of another same-shaped pill in the row above (SAVED_VIEWS
              status pills), which is what made it hard to spot before. */}
          <button
            type="button"
            onClick={() => setPanelOpen((o) => !o)}
            className={`flex items-center gap-1.5 h-7 px-2.5 rounded-md text-xs font-semibold transition-colors ${
              panelOpen ? "bg-white shadow-sm" : "hover:bg-white/60"
            }`}
            style={{ color: panelOpen ? "var(--primary)" : "var(--ink-secondary)" }}
          >
            <SlidersHorizontal size={12} />
            {t("filters")}
            {chips.length > 0 && (
              <span
                className="flex items-center justify-center min-w-[15px] h-[15px] px-1 rounded-full text-2xs font-semibold text-white"
                style={{ background: "var(--primary)" }}
              >
                {chips.length}
              </span>
            )}
            <ChevronDown
              size={12}
              className="transition-transform duration-200"
              style={{
                transform: panelOpen ? "rotate(180deg)" : "rotate(0deg)",
                color: panelOpen ? "var(--primary)" : "var(--ink-faint)",
              }}
            />
          </button>

          {chips.length > 0 && (
            <button
              type="button"
              onClick={() => router.push("/jobs")}
              className="text-xs whitespace-nowrap text-[var(--ink-muted)] hover:text-[var(--ink-primary)] underline underline-offset-2"
            >
              {t("clearFilters")}
            </button>
          )}
        </div>
      </div>

      <Collapsible open={panelOpen}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 pt-3 mt-1 border-t border-[var(--border)]">
          <div className="flex flex-col gap-1">
            <label className={labelClass}>{t("sort")}</label>
            <Select
              size="sm"
              value={effectiveSort}
              onValueChange={(v) => update("sort", v || null)}
              options={[
                { label: t("sortNewest"), value: "newest" },
                { label: t("sortOldest"), value: "oldest" },
                { label: t("sortCompany"), value: "company" },
                ...(profileId ? [{ label: t("sortFit"), value: "fit" }] : []),
              ]}
            />
          </div>

          {profiles.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className={labelClass}>{t("fitFor")}</label>
              <Select
              size="sm"
                value={profileId}
                onValueChange={(v) => update("profile_id", v || null)}
                options={[{ label: t("noProfile"), value: "" }, ...profiles.map((p) => ({ label: p.label, value: p.id }))]}
              />
            </div>
          )}

          {companies.length > 1 && (
            <div className="flex flex-col gap-1">
              <label className={labelClass}>{t("company")}</label>
              <Select
              size="sm"
                value={company}
                onValueChange={(v) => update("company", v || null)}
                options={[{ label: t("all"), value: "" }, ...companies.map((c) => ({ label: c, value: c }))]}
              />
            </div>
          )}

          {roleCategories.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className={labelClass}>{t("roleCategory")}</label>
              <Select
              size="sm"
                value={roleCategory}
                onValueChange={(v) => update("role_category", v || null)}
                options={[
                  { label: t("all"), value: "" },
                  ...roleCategories.map((category) => ({ label: category.split(" / ")[0], value: category })),
                ]}
              />
            </div>
          )}

          <div className="flex flex-col gap-1">
            <label className={labelClass}>{t("seniority")}</label>
            <Select
              size="sm"
              value={seniority}
              onValueChange={(v) => update("seniority", v || null)}
              options={[
                { label: t("all"), value: "" },
                ...Object.entries(SENIORITY_LABEL_KEY).map(([value, key]) => ({ label: t(key), value })),
              ]}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className={labelClass}>{t("confidence")}</label>
            <Select
              size="sm"
              value={confidence}
              onValueChange={(v) => update("confidence", v || null)}
              options={[
                { label: t("all"), value: "" },
                ...Object.entries(CONFIDENCE_LABEL_KEY).map(([value, key]) => ({ label: t(key), value })),
              ]}
            />
          </div>
        </div>
      </Collapsible>
    </div>
  );
}
