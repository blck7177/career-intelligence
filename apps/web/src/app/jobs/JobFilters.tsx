"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

interface ProfileOption {
  id: string;
  label: string;
}

interface JobFiltersProps {
  profiles: ProfileOption[];
  workstreams: string[];
}

export function JobFilters({ profiles, workstreams }: JobFiltersProps) {
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
      router.push(`/jobs?${params.toString()}`);
    },
    [router, sp],
  );

  const profileId = sp.get("profile_id") ?? "";
  const workstream = sp.get("workstream") ?? "";
  const seniority = sp.get("seniority") ?? "";
  const confidence = sp.get("confidence") ?? "";

  useEffect(() => {
    if (!profileId && profiles.length === 1) {
      update("profile_id", profiles[0].id);
    }
  }, [profileId, profiles, update]);

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {profiles.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-zinc-500 whitespace-nowrap">Fit for:</span>
          <select
            value={profileId}
            onChange={(e) => update("profile_id", e.target.value || null)}
            className="h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
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

      {workstreams.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-zinc-500 whitespace-nowrap">Workstream:</span>
          <select
            value={workstream}
            onChange={(e) => update("workstream", e.target.value || null)}
            className="h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400 max-w-[180px]"
          >
            <option value="">All</option>
            {workstreams.map((ws) => (
              <option key={ws} value={ws}>
                {ws.split(" / ")[0]}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <span className="text-xs text-zinc-500 whitespace-nowrap">Seniority:</span>
        <select
          value={seniority}
          onChange={(e) => update("seniority", e.target.value || null)}
          className="h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
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
        <span className="text-xs text-zinc-500 whitespace-nowrap">Confidence:</span>
        <select
          value={confidence}
          onChange={(e) => update("confidence", e.target.value || null)}
          className="h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          <option value="">All</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {(profileId || workstream || seniority || confidence) && (
        <button
          type="button"
          onClick={() => router.push("/jobs")}
          className="text-xs text-zinc-500 hover:text-zinc-800 underline underline-offset-2"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
