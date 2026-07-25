"use client";

import { useCallback, useState } from "react";
import { PlanToday } from "./PlanToday";
import { PipelineZone } from "./PipelineZone";
import { ReviewZone } from "./ReviewZone";

/** The Plan sub-view: three stacked zones — Today (execution), Pipeline
 *  (health), Review (weekly). One scroll container. A bump signal lets a
 *  Pipeline action (e.g. "Apply today") refresh the Today zone immediately. */
export function PlanView() {
  const [refreshSignal, setRefreshSignal] = useState(0);
  const bump = useCallback(() => setRefreshSignal((n) => n + 1), []);
  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-[var(--space-row-edge)] py-6 space-y-10">
        <PlanToday refreshSignal={refreshSignal} />
        <PipelineZone onChanged={bump} />
        <ReviewZone />
      </div>
    </div>
  );
}
