"use client";

import { Check, X, AlertTriangle, Ban } from "lucide-react";
import { BAND } from "@/lib/matchBand";

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "needs_review" | "cancelled";

interface StageVisual {
  bg: string;
  fg: string;
  ring: string;
  Icon: React.ElementType | null;
}

const TERMINAL_VISUAL: Record<string, StageVisual> = {
  succeeded: { bg: BAND.strong.bg, fg: BAND.strong.fg, ring: BAND.strong.ring, Icon: Check },
  failed: { bg: BAND.gaps.bg, fg: BAND.gaps.fg, ring: BAND.gaps.ring, Icon: X },
  needs_review: { bg: BAND.partial.bg, fg: BAND.partial.fg, ring: BAND.partial.ring, Icon: AlertTriangle },
  cancelled: { bg: "var(--muted)", fg: "var(--muted-foreground)", ring: "var(--ink-faint)", Icon: Ban },
};

const NEUTRAL_TRACK = "var(--border)";
const RUNNING_RING = "var(--primary)";

function stageIndex(status: RunStatus): 0 | 1 | 2 {
  if (status === "queued") return 0;
  if (status === "running") return 1;
  return 2;
}

interface RunStatusStepperProps {
  status: RunStatus;
  /** "sm" for dense list rows (dots + bars only); "md" for a labeled stepper. */
  size?: "sm" | "md";
  labels?: { queued: string; running: string; done: string };
  className?: string;
}

export function RunStatusStepper({ status, size = "md", labels, className }: RunStatusStepperProps) {
  const idx = stageIndex(status);
  const terminal = idx === 2 ? TERMINAL_VISUAL[status] ?? TERMINAL_VISUAL.cancelled : null;

  const dotSize = size === "sm" ? 6 : 9;
  const barWidth = size === "sm" ? 14 : 28;

  function dotColor(stage: 0 | 1 | 2): string {
    if (stage < idx) return RUNNING_RING; // already-passed stage
    if (stage === idx) return stage === 2 ? (terminal?.ring ?? NEUTRAL_TRACK) : RUNNING_RING;
    return NEUTRAL_TRACK; // not reached yet
  }

  function barColor(barIdx: 0 | 1): string {
    // bar 0 sits between stage 0/1, bar 1 between stage 1/2
    return idx > barIdx ? RUNNING_RING : NEUTRAL_TRACK;
  }

  const TerminalIcon = terminal?.Icon;

  return (
    <div className={`flex items-center ${className ?? ""}`}>
      {([0, 1, 2] as const).map((stage) => (
        <div key={stage} className="flex items-center">
          <div
            className="relative rounded-full flex items-center justify-center shrink-0 transition-colors duration-500"
            style={{
              width: stage === 2 && terminal ? dotSize + 6 : dotSize,
              height: stage === 2 && terminal ? dotSize + 6 : dotSize,
              backgroundColor: dotColor(stage),
            }}
          >
            {stage === 2 && terminal && TerminalIcon && size !== "sm" && (
              <TerminalIcon size={9} strokeWidth={3} color="white" />
            )}
            {stage === idx && stage !== 2 && (
              <span
                className="absolute inset-0 rounded-full animate-ping"
                style={{ backgroundColor: RUNNING_RING, opacity: 0.5 }}
              />
            )}
          </div>
          {stage < 2 && (
            <div
              className="h-[2px] shrink-0 transition-colors duration-500"
              style={{ width: barWidth, backgroundColor: barColor(stage as 0 | 1) }}
            />
          )}
        </div>
      ))}
      {labels && size !== "sm" && (
        <div className="ml-2.5 text-xs font-medium" style={{ color: terminal?.fg ?? "var(--muted-foreground)" }}>
          {idx === 0 ? labels.queued : idx === 1 ? labels.running : labels.done}
        </div>
      )}
    </div>
  );
}
