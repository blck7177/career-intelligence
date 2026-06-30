"use client";

import { useRouter } from "next/navigation";
import { useJobFavorite } from "@/hooks/useJobFavorite";

export function FavoriteButton({ jobId, initialFavorited }: { jobId: string; initialFavorited: boolean }) {
  const router = useRouter();
  const { favorited, loading, toggle } = useJobFavorite(jobId, initialFavorited, () => router.refresh());

  return (
    <button
      onClick={toggle}
      disabled={loading}
      aria-pressed={favorited}
      className="flex items-center gap-1.5 h-9 px-3.5 rounded-lg text-[13px] font-medium transition-colors disabled:opacity-50 shrink-0"
      style={
        favorited
          ? { background: "oklch(96% 0.04 95)", color: "oklch(45% 0.1 80)", border: "1px solid oklch(88% 0.06 90)" }
          : { background: "var(--muted)", color: "var(--muted-foreground)", border: "1px solid var(--border)" }
      }
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill={favorited ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
        <path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {favorited ? "Favorited" : "Favorite"}
    </button>
  );
}
