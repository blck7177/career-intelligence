"use client";

import { useTranslations } from "next-intl";
import { ThumbsDown } from "lucide-react";
import { useJobNotInterested } from "@/hooks/useJobNotInterested";
import { Tooltip } from "@/components/ui/tooltip";

interface Props {
  jobId: string;
  initialNotInterested: boolean;
  onToggled?: (notInterested: boolean) => void;
}

export function NotInterestedIconButton({ jobId, initialNotInterested, onToggled }: Props) {
  const t = useTranslations("notInterestedButton");
  const { notInterested, loading, toggle } = useJobNotInterested(jobId, initialNotInterested, onToggled);
  const label = notInterested ? t("remove") : t("add");

  return (
    <Tooltip content={label}>
      <button
        onClick={toggle}
        disabled={loading}
        aria-pressed={notInterested}
        aria-label={label}
        className="flex items-center justify-center w-7 h-7 rounded-md transition-colors disabled:opacity-50 shrink-0 hover:bg-[var(--muted)]"
        style={{ color: notInterested ? "oklch(45% 0.03 255)" : "var(--ink-faint)" }}
      >
        <ThumbsDown size={14} fill={notInterested ? "currentColor" : "none"} strokeWidth={1.8} />
      </button>
    </Tooltip>
  );
}
