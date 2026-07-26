"use client";

import { useTranslations } from "next-intl";
import { ThumbsDown } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { useJobNotInterested } from "@/hooks/useJobNotInterested";

export function NotInterestedButton({ jobId, initialNotInterested }: { jobId: string; initialNotInterested: boolean }) {
  const t = useTranslations("notInterestedButton");
  const router = useRouter();
  const { notInterested, loading, toggle } = useJobNotInterested(jobId, initialNotInterested, () => router.refresh());

  return (
    <button
      onClick={toggle}
      disabled={loading}
      aria-pressed={notInterested}
      className="flex items-center gap-1.5 h-9 px-3.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 shrink-0"
      style={
        notInterested
          ? { background: "oklch(95% 0.01 255)", color: "oklch(45% 0.03 255)", border: "1px solid oklch(87% 0.02 255)" }
          : { background: "var(--muted)", color: "var(--muted-foreground)", border: "1px solid var(--border)" }
      }
    >
      <ThumbsDown size={14} fill={notInterested ? "currentColor" : "none"} strokeWidth={1.8} />
      {notInterested ? t("dismissed") : t("notInterested")}
    </button>
  );
}
