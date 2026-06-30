"use client";

import { useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { favoriteJob, unfavoriteJob } from "@/api/client";

export function useJobFavorite(
  jobId: string,
  initialFavorited: boolean,
  onToggled?: (favorited: boolean) => void,
) {
  const getToken = useApiToken();
  const [favorited, setFavorited] = useState(initialFavorited);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    setLoading(true);
    try {
      const token = await getToken();
      const next = !favorited;
      if (next) {
        await favoriteJob(jobId, token);
      } else {
        await unfavoriteJob(jobId, token);
      }
      setFavorited(next);
      onToggled?.(next);
    } finally {
      setLoading(false);
    }
  }

  return { favorited, loading, toggle };
}
