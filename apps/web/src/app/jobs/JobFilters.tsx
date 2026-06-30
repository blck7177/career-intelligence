"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

interface ProfileOption {
  id: string;
  label: string;
}

interface JobFiltersProps {
  profiles: ProfileOption[];
  roleCategories: string[];
  companies: string[];
}

export function JobFilters({ profiles, roleCategories, companies }: JobFiltersProps) {
  const router = useRouter();
  const sp = useSearchParams();

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

  const selectClass =
    "h-8 rounded-md border border-zinc-200 bg-white px-2.5 text-[13px] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50";

  return (
    <div className="flex flex-wrap gap-2.5 items-center">
      {/* Sort */}
      <div className="flex items-center gap-1.5">
        <span className="text-[13px] text-zinc-500 whitespace-nowrap">Sort:</span>
        <select
          value={sort}
          onChange={(e) => update("sort", e.target.value || null)}
          className={selectClass}
        >
          <option value="">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="company">Company A→Z</option>
          {profileId && <option value="fit">Fit Score</option>}
        </select>
      </div>

      {profiles.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] text-zinc-500 whitespace-nowrap">Fit for:</span>
          <select
            value={profileId}
            onChange={(e) => update("profile_id", e.target.value || null)}
            className={selectClass}
          >
            <option value="">— no profile —</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Company */}
      {companies.length > 1 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] text-zinc-500 whitespace-nowrap">Company:</span>
          <select
            value={company}
            onChange={(e) => update("company", e.target.value || null)}
            className={`${selectClass} max-w-[180px]`}
          >
            <option value="">All</option>
            {companies.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      )}

      {roleCategories.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] text-zinc-500 whitespace-nowrap">Role category:</span>
          <select
            value={roleCategory}
            onChange={(e) => update("role_category", e.target.value || null)}
            className={`${selectClass} max-w-[180px]`}
          >
            <option value="">All</option>
            {roleCategories.map((category) => (
              <option key={category} value={category}>
                {category.split(" / ")[0]}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <span className="text-[13px] text-zinc-500 whitespace-nowrap">Seniority:</span>
        <select
          value={seniority}
          onChange={(e) => update("seniority", e.target.value || null)}
          className={selectClass}
        >
          <option value="">All</option>
          <option value="junior">Junior</option>
          <option value="mid">Mid</option>
          <option value="senior">Senior</option>
          <option value="lead">Lead / Principal</option>
          <option value="director">Director+</option>
        </select>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-[13px] text-zinc-500 whitespace-nowrap">Confidence:</span>
        <select
          value={confidence}
          onChange={(e) => update("confidence", e.target.value || null)}
          className={selectClass}
        >
          <option value="">All</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {(profileId || roleCategory || seniority || confidence || company || sort) && (
        <button
          type="button"
          onClick={() => router.push("/jobs")}
          className="text-[13px] text-zinc-500 hover:text-zinc-800 underline underline-offset-2"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
