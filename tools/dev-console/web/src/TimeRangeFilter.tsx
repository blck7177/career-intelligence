import type { TimeRange } from "./types";

interface Props {
  selected: TimeRange;
  onChange: (range: TimeRange) => void;
}

const OPTIONS: { label: string; value: TimeRange }[] = [
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
  { label: "All", value: "all" },
];

export function TimeRangeFilter({ selected, onChange }: Props) {
  return (
    <div className="time-range-filter">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          className={`time-range-btn ${selected === o.value ? "active" : ""}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
