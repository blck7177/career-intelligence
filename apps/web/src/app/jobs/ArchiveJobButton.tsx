"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { archiveJob } from "@/api/client";

export function ArchiveJobButton({ jobId }: { jobId: string }) {
  const getToken = useApiToken();
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleArchive() {
    setLoading(true);
    try {
      const token = await getToken();
      await archiveJob(jobId, token);
      router.refresh();
    } catch {
      setLoading(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <span className="flex items-center gap-1.5">
        <button
          onClick={handleArchive}
          disabled={loading}
          className="text-[12px] font-medium text-rose-600 hover:text-rose-800 disabled:opacity-50"
        >
          {loading ? "Removing…" : "Confirm"}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-[12px] text-zinc-400 hover:text-zinc-600"
        >
          Cancel
        </button>
      </span>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      className="text-[12px] text-zinc-400 hover:text-rose-500 transition-colors"
    >
      Remove
    </button>
  );
}
