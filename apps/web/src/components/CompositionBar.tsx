export interface CompositionSegment {
  key: string;
  count: number;
  label: string;
  color: string;
}

interface CompositionBarProps {
  segments: CompositionSegment[];
  ariaLabel: string;
  /** Compact = tiny bar with a title tooltip, no legend (for inline headers). */
  compact?: boolean;
  className?: string;
}

/**
 * Part-to-whole segmented bar: renders each non-zero segment proportional to
 * its share of the total, separated by the standard 2px surface gap, with a
 * legend of color-dot + label + count underneath (full size only).
 */
export function CompositionBar({ segments, ariaLabel, compact, className }: CompositionBarProps) {
  const total = segments.reduce((sum, s) => sum + s.count, 0);
  if (total === 0) return null;
  const visible = segments.filter((s) => s.count > 0);

  if (compact) {
    return (
      <div className={className} title={visible.map((s) => `${s.label}: ${s.count}`).join(" · ")}>
        <div className="flex h-1.5 w-16 overflow-hidden rounded-full bg-[var(--muted)]">
          {visible.map((s, i) => (
            <div
              key={s.key}
              style={{ width: `${(s.count / total) * 100}%`, backgroundColor: s.color, marginLeft: i === 0 ? 0 : 1.5 }}
              className="h-full"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--muted)]" role="img" aria-label={ariaLabel}>
        {visible.map((s, i) => (
          <div
            key={s.key}
            title={`${s.label}: ${s.count}`}
            style={{ width: `${(s.count / total) * 100}%`, backgroundColor: s.color, marginLeft: i === 0 ? 0 : 2 }}
            className="h-full first:rounded-l-full last:rounded-r-full"
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {visible.map((s) => (
          <div key={s.key} className="flex items-center gap-1.5 text-xs text-[var(--ink-muted)]">
            <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
            {s.label} <span className="font-semibold tabular-nums text-[var(--ink-secondary)]">{s.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
