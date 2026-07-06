"use client";

import { WORKSPACE_FUNCTIONS } from "@/lib/workspace/workspaceTypes";
import type { WorkspaceFunctionId } from "@/lib/workspace/workspaceTypes";
import {
  Search,
  FileText,
  UserCheck,
  Activity,
  Briefcase,
} from "lucide-react";

interface FunctionPanelProps {
  activeFunction: WorkspaceFunctionId;
  onSelect: (fn: WorkspaceFunctionId) => void;
}

const ICONS: Record<WorkspaceFunctionId, React.ReactNode> = {
  discovery: <Search size={15} />,
  job_report: <FileText size={15} />,
  fit_report: <UserCheck size={15} />,
  runs: <Activity size={15} />,
  jobs: <Briefcase size={15} />,
};

export function FunctionPanel({ activeFunction, onSelect }: FunctionPanelProps) {
  // Only show action-triggering modes; Runs/Jobs are now in the main sidebar nav
  const SHOWN_FUNCTIONS: WorkspaceFunctionId[] = ["discovery", "job_report", "fit_report"];

  return (
    <nav className="py-3">
      <p className="px-4 pb-2 text-xs font-semibold text-[var(--ink-muted)] uppercase tracking-wider">
        Search Setup
      </p>
      <ul className="space-y-0.5">
        {WORKSPACE_FUNCTIONS.filter((fn) => SHOWN_FUNCTIONS.includes(fn.id)).map((fn) => {
          const isActive = activeFunction === fn.id;
          const isDisabled = !fn.available;

          return (
            <li key={fn.id}>
              <button
                disabled={isDisabled}
                onClick={() => !isDisabled && onSelect(fn.id)}
                className={[
                  "w-full flex items-center gap-2.5 px-4 py-2 text-sm rounded-none transition-colors text-left",
                  isActive
                    ? "bg-[var(--primary)] text-white font-medium"
                    : isDisabled
                    ? "text-[var(--ink-muted)] cursor-not-allowed"
                    : "text-[var(--ink-secondary)] hover:bg-[var(--muted)] hover:text-[var(--ink-primary)]",
                ].join(" ")}
              >
                <span className={isActive ? "text-white" : isDisabled ? "text-[var(--ink-faint)]" : "text-[var(--ink-muted)]"}>
                  {ICONS[fn.id]}
                </span>
                <span className="flex-1">{fn.label}</span>
                {fn.comingSoon && (
                  <span className="text-xs text-[var(--ink-muted)] font-normal">soon</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
