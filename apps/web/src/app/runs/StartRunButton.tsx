"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { createRun } from "@/api/client";
import { Plus, Loader2 } from "lucide-react";

const WORKSPACE_ID = process.env.NEXT_PUBLIC_WORKSPACE_ID ?? "ws_default";

export function StartRunButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      const run = await createRun({
        run_type: "job_discovery",
        workspace_id: WORKSPACE_ID,
        input_snapshot: {},
      });
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setLoading(false);
    }
  }

  return (
    <div>
      <Button onClick={handleClick} disabled={loading} size="sm">
        {loading ? (
          <Loader2 size={14} className="animate-spin mr-1.5" />
        ) : (
          <Plus size={14} className="mr-1.5" />
        )}
        New Discovery Run
      </Button>
      {error && <p className="text-xs text-rose-600 mt-1">{error}</p>}
    </div>
  );
}
