"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { SlidersHorizontal, X } from "lucide-react";
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
      router.push(`/jobs?${params.toString()}`);
    },
    [router, sp],
  );

  const profileId = sp.get("profile_id") ?? "";
  const roleCategory = sp.get("role_category") ?? "";
  const seniority = sp.get("seniority") ?? "";
  const confidence = sp.get("confidence") ?? "";
  const company = sp.get("company") ?? "";
  const sort = sp.get("sort") ?? "";

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
  if (sort && SORT_LABEL_KEY[sort]) {
    chips.push({ key: "sort", label: `${t("sort")} ${t(SORT_LABEL_KEY[sort])}`, onRemove: () => update("sort", null) });
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

  const labelClass = "text-[11.5px] font-medium text-[var(--ink-muted)]";

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setPanelOpen((o) => !o)}
          className="flex items-center gap-1.5 h-8 px-3 rounded-full text-[13px] font-medium border border-dashed transition-colors"
          style={
            panelOpen
              ? { borderColor: "var(--primary)", color: "var(--primary)", background: "var(--secondary)" }
              : { borderColor: "var(--border)", color: "var(--ink-secondary)" }
          }
        >
          <SlidersHorizontal size={13} />
          {t("filters")}
          {chips.length > 0 && (
            <span
              className="flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full text-[10px] font-semibold text-white"
              style={{ background: "var(--primary)" }}
            >
              {chips.length}
            </span>
          )}
        </button>

        {chips.map((chip) => (
          <span
            key={chip.key}
            className="flex items-center gap-1.5 h-8 pl-3 pr-1.5 rounded-full text-[12.5px] font-medium"
            style={{ background: "var(--secondary)", color: "var(--secondary-foreground)" }}
          >
            {chip.label}
            <button
              type="button"
              onClick={chip.onRemove}
              aria-label={t("clearFilters")}
              className="flex items-center justify-center w-4 h-4 rounded-full hover:bg-black/10 transition-colors"
            >
              <X size={11} />
            </button>
          </span>
        ))}

        {chips.length > 0 && (
          <button
            type="button"
            onClick={() => router.push("/jobs")}
            className="text-[12.5px] text-[var(--ink-muted)] hover:text-[var(--ink-primary)] underline underline-offset-2"
          >
            {t("clearFilters")}
          </button>
        )}
      </div>

      <Collapsible open={panelOpen}>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-4 grid grid-cols-2 gap-3.5">
          <div className="flex flex-col gap-1">
            <label className={labelClass}>{t("sort")}</label>
            <Select
              size="sm"
              value={sort}
              onValueChange={(v) => update("sort", v || null)}
              options={[
                { label: t("sortNewest"), value: "" },
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
