import Link from "next/link";
import { Briefcase, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function JobsPanel() {
  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-zinc-800">Jobs</h2>
        <p className="text-xs text-zinc-500 mt-0.5">Browse your discovered job database.</p>
      </div>

      <div className="flex flex-col items-center justify-center py-8 gap-3 rounded-lg border border-zinc-200 bg-zinc-50">
        <Briefcase size={24} className="text-zinc-400" />
        <div className="text-center">
          <p className="text-sm font-medium text-zinc-600">Full job database available</p>
          <p className="text-xs text-zinc-400 mt-1">
            View, filter, and analyze all discovered jobs on the Jobs page.
          </p>
        </div>
        <Link href="/jobs">
          <Button size="sm" variant="outline" className="gap-1.5">
            Open Job Database
            <ArrowRight size={13} />
          </Button>
        </Link>
      </div>
    </div>
  );
}
