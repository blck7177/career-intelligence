"use client";

import { useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { markJobNotInterested, unmarkJobNotInterested } from "@/api/client";
import { toast } from "@/components/ui/toaster";

export function useJobNotInterested(
  jobId: string,
  initialNotInterested: boolean,
  onToggled?: (notInterested: boolean) => void,
) {
  const getToken = useApiToken();
  const [notInterested, setNotInterested] = useState(initialNotInterested);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    setLoading(true);
    try {
      const token = await getToken();
      const next = !notInterested;
      if (next) {
        await markJobNotInterested(jobId, token);
      } else {
        await unmarkJobNotInterested(jobId, token);
      }
      setNotInterested(next);
      onToggled?.(next);
    } catch {
      toast.error("Couldn't update — try again");
    } finally {
      setLoading(false);
    }
  }

  return { notInterested, loading, toggle };
}
