"use client";

import { useTranslations } from "next-intl";
import { useJobFavorite } from "@/hooks/useJobFavorite";

interface Props {
  jobId: string;
  initialFavorited: boolean;
  onToggled?: (favorited: boolean) => void;
}

export function FavoriteStarButton({ jobId, initialFavorited, onToggled }: Props) {
  const t = useTranslations("favoriteButton");
  const { favorited, loading, toggle } = useJobFavorite(jobId, initialFavorited, onToggled);

  return (
    <button
      onClick={toggle}
      disabled={loading}
      aria-pressed={favorited}
      aria-label={favorited ? t("remove") : t("add")}
      className="flex items-center justify-center w-7 h-7 rounded-md transition-colors disabled:opacity-50 shrink-0 hover:bg-zinc-100"
      style={{ color: favorited ? "oklch(60% 0.15 80)" : "oklch(72% 0.01 275)" }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill={favorited ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
        <path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}
