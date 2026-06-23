"use client";

import { useState, useEffect } from "react";
import { listEvents } from "@/api/client";
import type { TaskEventRead } from "@/api/client";
import { fmtTs } from "@/lib/utils";
import { Clock } from "lucide-react";

interface EventsViewProps {
  runId: string;
}

export function EventsView({ runId }: EventsViewProps) {
  const [events, setEvents] = useState<TaskEventRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listEvents(runId)
      .then(setEvents)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load events"))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <p className="text-xs text-zinc-400 py-4 text-center">Loading events…</p>;
  if (error) return <p className="text-xs text-rose-600">{error}</p>;
  if (events.length === 0) return <p className="text-xs text-zinc-400 py-4 text-center">No events yet.</p>;

  return (
    <ul className="space-y-0">
      {events.map((event) => (
        <li
          key={event.id}
          className="flex gap-3 py-2.5 border-b border-zinc-100 last:border-0"
        >
          <Clock size={12} className="text-zinc-300 mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-zinc-700">{event.event_type}</p>
            {event.message && (
              <p className="text-xs text-zinc-500 mt-0.5 break-words">{event.message}</p>
            )}
            <p className="text-xs text-zinc-400 mt-0.5">{fmtTs(event.created_at)}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}
