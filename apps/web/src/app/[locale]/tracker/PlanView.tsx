"use client";

import { PlanToday } from "./PlanToday";
import { PipelineZone } from "./PipelineZone";
import { ReviewZone } from "./ReviewZone";

/** The Plan sub-view: three stacked zones — Today (execution), Pipeline
 *  (health), Review (weekly). One scroll container. */
export function PlanView() {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-[var(--space-row-edge)] py-6 space-y-10">
        <PlanToday />
        <PipelineZone />
        <ReviewZone />
      </div>
    </div>
  );
}
