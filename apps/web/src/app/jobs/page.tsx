"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import { Building2, MapPin, Plus, ExternalLink, Search } from "lucide-react";

type StatusFilter = "all" | "discovered" | "reportable" | "stale" | "invalid";
type SortKey = "newest" | "oldest" | "company";

const SAVED_VIEWS: { label: string; status: StatusFilter }[] = [
  { label: "All", status: "all" },
  { label: "Has Report", status: "reportable" },
  { label: "Needs Report", status: "discovered" },
  { label: "Stale", status: "stale" },
];

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  if (status === "stale") return "bg-zinc-100 text-zinc-600";
  return "bg-zinc-100 text-zinc-600";
}

function JobRow({ job }: { job: JobRead }) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="flex items-start justify-between border border-zinc-200 rounded-lg p-4 hover:bg-zinc-50 transition-colors gap-4"
    >
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-semibold text-zinc-900 truncate">{job.title}</p>
          <Badge className={jobStatusBg(job.status) + " text-xs shrink-0"}>
            {job.status}
          </Badge>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-500 flex-wrap">
          <span className="flex items-center gap-1">
            <Building2 size={11} />
            {job.company}
          </span>
          {job.location && (
            <span className="flex items-center gap-1">
              <MapPin size={11} />
              {job.location}
            </span>
          )}
          <span className="text-zinc-400">{job.source_type}</span>
        </div>
        <p className="text-xs text-zinc-400">Discovered {fmtTs(job.created_at.toString())}</p>
      </div>
      <ExternalLink size={14} className="text-zinc-300 shrink-0 mt-0.5" />
    </Link>
  );
}

export default function JobsPage() {
  const { getToken } = useAuth();
  const [allJobs, setAllJobs] = useState<JobRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("newest");

  useEffect(() => {
    setLoading(true);
    setFetchError(null);
    getToken()
      .then((token) => listJobs(token))
      .then((list) => setAllJobs(list.items))
      .catch((err) => setFetchError(err instanceof Error ? err.message : "Failed to load jobs"))
      .finally(() => setLoading(false));
  }, [getToken]);

  const filteredJobs = useMemo(() => {
    let jobs = allJobs;

    if (statusFilter !== "all") {
      jobs = jobs.filter((j) => j.status === statusFilter);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      jobs = jobs.filter(
        (j) =>
          j.title.toLowerCase().includes(q) ||
          j.company.toLowerCase().includes(q),
      );
    }

    return [...jobs].sort((a, b) => {
      if (sortKey === "newest") {
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      }
      if (sortKey === "oldest") {
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      }
      // company A→Z
      return a.company.localeCompare(b.company);
    });
  }, [allJobs, statusFilter, searchQuery, sortKey]);

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Job Database</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {loading
              ? "Loading…"
              : `${filteredJobs.length} of ${allJobs.length} job${allJobs.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        <Link href="/workspace">
          <Button size="sm">
            <Plus size={14} className="mr-1.5" />
            Add Jobs
          </Button>
        </Link>
      </div>

      {/* Saved views */}
      <div className="flex gap-2 flex-wrap">
        {SAVED_VIEWS.map((view) => (
          <button
            key={view.status}
            onClick={() => setStatusFilter(view.status)}
            className={[
              "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
              statusFilter === view.status
                ? "border-zinc-800 bg-zinc-800 text-white"
                : "border-zinc-300 text-zinc-600 hover:border-zinc-400 hover:text-zinc-900",
            ].join(" ")}
          >
            {view.label}
            {view.status !== "all" && allJobs.length > 0 && (
              <span className={[
                "ml-1.5 text-[10px]",
                statusFilter === view.status ? "text-zinc-300" : "text-zinc-400",
              ].join(" ")}>
                {allJobs.filter((j) => j.status === view.status).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-48">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            placeholder="Search title or company…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded border border-zinc-300 bg-white pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
          />
        </div>

        {/* Status filter (segmented) — only show when not using saved view */}
        <div className="flex gap-1">
          {(["all", "discovered", "reportable", "stale", "invalid"] as StatusFilter[]).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={[
                "px-2.5 py-1.5 rounded border text-xs transition-colors",
                statusFilter === s
                  ? "border-zinc-800 bg-zinc-800 text-white"
                  : "border-zinc-200 text-zinc-500 hover:border-zinc-300 hover:text-zinc-700",
              ].join(" ")}
            >
              {s === "all" ? "All" : s}
            </button>
          ))}
        </div>

        {/* Sort */}
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="company">Company A→Z</option>
        </select>
      </div>

      {/* Error */}
      {fetchError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {fetchError}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 rounded-lg border border-zinc-100 bg-zinc-50 animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty states */}
      {!loading && allJobs.length === 0 && !fetchError && (
        <div className="rounded-lg border border-dashed border-zinc-300 p-12 text-center space-y-3">
          <p className="text-zinc-500 text-sm font-medium">No jobs yet</p>
          <p className="text-zinc-400 text-xs">
            Run a Discovery search to find and ingest job listings.
          </p>
          <Link href="/workspace">
            <Button size="sm" variant="outline" className="mt-2">
              <Plus size={13} className="mr-1.5" />
              Start Discovery
            </Button>
          </Link>
        </div>
      )}

      {!loading && allJobs.length > 0 && filteredJobs.length === 0 && (
        <div className="rounded-lg border border-dashed border-zinc-200 p-8 text-center">
          <p className="text-zinc-500 text-sm">No jobs match the current filters.</p>
          <button
            onClick={() => { setStatusFilter("all"); setSearchQuery(""); }}
            className="mt-2 text-xs text-zinc-400 hover:text-zinc-700 underline"
          >
            Clear filters
          </button>
        </div>
      )}

      {/* Job list */}
      {!loading && filteredJobs.length > 0 && (
        <div className="space-y-2">
          {filteredJobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}
