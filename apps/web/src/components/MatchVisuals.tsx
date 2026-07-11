import { bandOf, BAND } from "@/lib/matchBand";

/** Compact "N/100" pill, colored by the shared strong/partial/gaps band system. */
export function ScoreBadge({ score, size = "sm" }: { score: number; size?: "sm" | "md" }) {
  const b = BAND[bandOf(score)];
  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold tabular-nums ${
        size === "sm" ? "px-2.5 py-0.5 text-xs" : "px-3 py-1 text-sm"
      }`}
      style={{ backgroundColor: b.bg, color: b.fg }}
    >
      {score}/100
    </span>
  );
}

/** Gap-severity chip: blocking -> gaps band, significant -> partial band, else neutral. */
export function SeverityChip({ severity }: { severity: string }) {
  const tone = severity === "blocking" ? BAND.gaps : severity === "significant" ? BAND.partial : null;
  return (
    <span
      className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${tone ? "" : "bg-[var(--muted)] text-[var(--ink-secondary)]"}`}
      style={tone ? { backgroundColor: tone.bg, color: tone.fg } : undefined}
    >
      {severity}
    </span>
  );
}
