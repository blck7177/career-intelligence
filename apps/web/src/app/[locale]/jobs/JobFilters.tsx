"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { SlidersHorizontal, X } from "lucide-react";
import { Collapsible } from "@/components/Collapsible";

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

  const selectClass =
    "h-8 rounded-md border border-[var(--border)] bg-white px-2.5 text-[13px] text-[var(--ink-secondary)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50";
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
            <select value={sort} onChange={(e) => update("sort", e.target.value || null)} className={selectClass}>
              <option value="">{t("sortNewest")}</option>
              <option value="oldest">{t("sortOldest")}</option>
              <option value="company">{t("sortCompany")}</option>
              {profileId && <option value="fit">{t("sortFit")}</option>}
            </select>
          </div>

          {profiles.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className={labelClass}>{t("fitFor")}</label>
              <select value={profileId} onChange={(e) => update("profile_id", e.target.value || null)} className={selectClass}>
                <option value="">{t("noProfile")}</option>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {companies.length > 1 && (
            <div className="flex flex-col gap-1">
              <label className={labelClass}>{t("company")}</label>
              <select value={company} onChange={(e) => update("company", e.target.value || null)} className={selectClass}>
                <option value="">{t("all")}</option>
                {companies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          )}

          {roleCategories.length > 0 && (
            <div className="flex flex-col gap-1">
              <label className={labelClass}>{t("roleCategory")}</label>
              <select value={roleCategory} onChange={(e) => update("role_category", e.target.value || null)} className={selectClass}>
                <option value="">{t("all")}</option>
                {roleCategories.map((category) => (
                  <option key={category} value={category}>
                    {category.split(" / ")[0]}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <label className={labelClass}>{t("seniority")}</label>
            <select value={seniority} onChange={(e) => update("seniority", e.target.value || null)} className={selectClass}>
              <option value="">{t("all")}</option>
              <option value="junior">{t("seniorityJunior")}</option>
              <option value="mid">{t("seniorityMid")}</option>
              <option value="senior">{t("senioritySenior")}</option>
              <option value="lead">{t("seniorityLead")}</option>
              <option value="director">{t("seniorityDirector")}</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className={labelClass}>{t("confidence")}</label>
            <select value={confidence} onChange={(e) => update("confidence", e.target.value || null)} className={selectClass}>
              <option value="">{t("all")}</option>
              <option value="high">{t("confidenceHigh")}</option>
              <option value="medium">{t("confidenceMedium")}</option>
              <option value="low">{t("confidenceLow")}</option>
            </select>
          </div>
        </div>
      </Collapsible>
    </div>
  );
}
