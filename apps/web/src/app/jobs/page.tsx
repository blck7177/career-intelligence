"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useApiToken } from "@/hooks/useApiToken";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import { Building2, MapPin, Plus, Search, FileText, ChevronRight } from "lucide-react";

type StatusFilter = "all" | "discovered" | "reportable" | "stale" | "invalid";
type SortKey = "newest" | "oldest" | "company";

const SAVED_VIEWS: { label: string; status: StatusFilter }[] = [
  { label: "All", status: "all" },
  { label: "Report Ready", status: "reportable" },
  { label: "Needs Report", status: "discovered" },
  { label: "Stale", status: "stale" },
];

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  if (status === "stale") return "bg-zinc-100 text-zinc-500";
  return "bg-zinc-100 text-zinc-600";
}

function jobStatusLabel(status: string): string {
  const MAP: Record<string, string> = {
    reportable: "Report Ready",
    discovered: "Needs Report",
    stale: "Stale",
    invalid: "Invalid",
  };
  return MAP[status] ?? status;
}

function statusDot(status: string): string {
  if (status === "reportable") return "bg-emerald-400";
  if (status === "discovered") return "bg-blue-400";
  if (status === "stale") return "bg-zinc-300";
  if (status === "invalid") return "bg-rose-400";
  return "bg-zinc-300";
}

function JobRow({ job }: { job: JobRead }) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="flex items-start gap-3 border border-zinc-200 rounded-lg bg-white p-4 hover:border-zinc-300 hover:shadow-sm transition-all group"
    >
      {/* Status dot */}
      <div className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${statusDot(job.status)}`} />

      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-semibold text-zinc-900 leading-snug truncate">{job.title}</p>
          <Badge className={jobStatusBg(job.status) + " text-[10px] shrink-0"}>
            {jobStatusLabel(job.status)}
          </Badge>
        </div>
        <div className="flex items-center gap-2.5 text-xs text-zinc-500 flex-wrap">
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
          <span className="text-zinc-300">·</span>
          <span className="text-zinc-400 capitalize">{job.source_type?.replace(/_/g, " ")}</span>
        </div>
        <p className="text-xs text-zinc-400">Discovered {fmtTs(job.created_at.toString())}</p>
      </div>

      {/* Right */}
      <div className="shrink-0 flex flex-col items-end gap-1.5 pt-0.5">
        {job.status === "reportable" && (
          <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600 font-medium">
            <FileText size={10} />
            Report ready
          </span>
        )}
        <ChevronRight
          size={14}
          className="text-zinc-300 group-hover:text-zinc-500 transition-colors"
        />
      </div>
    </Link>
  );
}

export default function JobsPage() {
  const getToken = useApiToken();
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
      if (sortKey === "newest") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      if (sortKey === "oldest") return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      return a.company.localeCompare(b.company);
    });
  }, [allJobs, statusFilter, searchQuery, sortKey]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Role Inbox</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {loading
              ? "Loading…"
              : `${filteredJobs.length} of ${allJobs.length} role${allJobs.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        <Link href="/workspace">
          <Button size="sm">
            <Plus size={14} className="mr-1.5" />
            New Discovery
          </Button>
        </Link>
      </div>

      {/* Saved views */}
      <div className="flex gap-2 flex-wrap">
        {SAVED_VIEWS.map((view) => {
          const count =
            view.status !== "all"
              ? allJobs.filter((j) => j.status === view.status).length
              : allJobs.length;
          const active = statusFilter === view.status;
          return (
            <button
              key={view.status}
              onClick={() => setStatusFilter(view.status)}
              className={[
                "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
                active
                  ? "border-indigo-600 bg-indigo-600 text-white"
                  : "border-zinc-300 text-zinc-600 hover:border-zinc-400 hover:text-zinc-900",
              ].join(" ")}
            >
              {view.label}
              {allJobs.length > 0 && (
                <span
                  className={["ml-1.5 text-[10px]", active ? "text-indigo-200" : "text-zinc-400"].join(" ")}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            placeholder="Search title or company…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded border border-zinc-300 bg-white pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
          />
        </div>
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="company">Company A→Z</option>
        </select>
      </div>

      {fetchError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {fetchError}
        </div>
      )}

      {loading && (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 rounded-lg border border-zinc-100 bg-zinc-50 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && allJobs.length === 0 && !fetchError && (
        <div className="rounded-lg border border-dashed border-zinc-300 p-12 text-center space-y-3">
          <p className="text-zinc-500 text-sm font-medium">Role Inbox is empty</p>
          <p className="text-zinc-400 text-xs">
            Run a Discovery search to find and import matching roles.
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
          <p className="text-zinc-500 text-sm">No roles match the current filters.</p>
          <button
            onClick={() => {
              setStatusFilter("all");
              setSearchQuery("");
            }}
            className="mt-2 text-xs text-zinc-400 hover:text-zinc-700 underline"
          >
            Clear filters
          </button>
        </div>
      )}

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
