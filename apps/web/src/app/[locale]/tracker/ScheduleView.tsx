"use client";

import { useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { updateAction } from "@/api/client";
import type { ActionRead, PlannerWeekInterview } from "@/api/client";
import { useApiToken } from "@/hooks/useApiToken";
import { toast } from "@/components/ui/toaster";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { optionPillVariants } from "@/components/ui/option-pill-variants";
import { localWallTimeUtc } from "@/lib/quickParse";
import { estOf, fmtMinutes } from "./capacity";
import { usePlannerData } from "./usePlannerData";
import {
  BLOCK_INSET, SLOT, SLOT_H,
  bandFor, fmtClock, geometryFor, minutesOfDay, mondayOf, monthGrid, rowsFor, shiftMonth, snapDuration,
} from "./scheduleGrid";

/** Sizes taken from the Compass mockup. SLOT_H lives in scheduleGrid because
 *  the geometry maths needs it; ROW_PX is the same number as a Tailwind-side
 *  string so the two cannot drift apart silently. */
const ROW_PX = `${SLOT_H}px`;
/** The time-axis column. */
const AXIS_W = "44px";
/** Minimum width of one day column, below which the grid scrolls instead of
 *  compressing: 44 + 7×108 = 800. */
const GRID_MIN = "800px";

/** Column headers. The server returns Mon..Sun and the INDEX is the weekday —
 *  parsing the date string to work out which day it is would be a second,
 *  quietly different definition of where a week starts. */
const WEEKDAY_KEYS = [
  "weekdayMon", "weekdayTue", "weekdayWed", "weekdayThu", "weekdayFri", "weekdaySat", "weekdaySun",
] as const;

/** `duration` is the honest estimate and is what day totals add up; `slot` is
 *  what the block OCCUPIES once dropped, rounded to the grid. They differ for a
 *  20-minute task, which takes the whole half-hour it lands in — and the block's
 *  height and its own label have to agree about which of the two they mean, or
 *  the picture says one thing and the text another. */
type Item =
  | { kind: "block"; action: ActionRead; start: number; duration: number | null; slot: number | null; title: string }
  | { kind: "interview"; interview: PlannerWeekInterview; start: number; duration: number | null; slot: number | null; title: string };

export function ScheduleView() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  /** Which week is on screen. undefined = this week, which is also what the
   *  server defaults to. This state is deliberately LOCAL to the schedule view:
   *  `is_today` is only true inside the current week, and seven places in the
   *  Today view read it as "the server's idea of today" — one of them a guard
   *  that fails OPEN rather than degrading. Paging back a month must not take
   *  the day identity of another view with it. */
  const [weekParam, setWeekParam] = useState<string | undefined>(undefined);
  const data = usePlannerData({ schedule: true, week: weekParam });
  const { week, settings, blocks, tray, refresh } = data;
  const tz = settings?.timezone ?? null;
  const cap = settings?.daily_cap_minutes ?? 0;
  // Remembered rather than re-read: once paged away from the current week the
  // server stops marking any day as today, and the picker would lose the one
  // date worth pointing at. Never computed from the browser clock.
  const todayRef = useRef<string | null>(null);
  const serverToday = week?.days.find((d) => d.is_today)?.date ?? null;
  if (serverToday) todayRef.current = serverToday;
  const [monthAnchor, setMonthAnchor] = useState<string | null>(null);
  const anchor = monthAnchor ?? week?.week_start ?? null;
  const viewingThisWeek = weekParam === undefined;
  /** Id being dragged. Also the flag that makes slots accept a drop: without
   *  it every dragged file from the desktop would light the grid up. */
  const [dragId, setDragId] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  /** The to-do the picker is open for — the keyboard and touch path, which the
   *  mockup has neither of. Drag-and-drop alone would leave the grid unusable
   *  with a keyboard and invisible on a phone. */
  const [picking, setPicking] = useState<ActionRead | null>(null);
  const [busy, setBusy] = useState(false);

  async function place(actionId: string, date: string, minutes: number) {
    if (!tz || busy) return;
    setBusy(true);
    try {
      const token = await getToken();
      // The wall time the user pointed at, encoded in the WORKSPACE zone — the
      // slot they dropped on is a time of day there, not in their browser.
      await updateAction(
        actionId,
        // snooze_days is required by the generated type (it has a server
        // default); it is ignored by every op but snooze.
        { op: "schedule", snooze_days: 1, scheduled_at: localWallTimeUtc(date, tz, minutes) },
        token,
      );
      await refresh("schedule");
    } catch {
      toast.error(t("scheduleFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function unplace(actionId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const token = await getToken();
      await updateAction(actionId, { op: "unschedule", snooze_days: 1 }, token);
      await refresh("schedule");
    } catch {
      toast.error(t("scheduleFailed"));
    } finally {
      setBusy(false);
    }
  }

  /** One bucket per day of the week the server resolved. Days come from the
   *  server (Mon..Sun, index = weekday), never from parsing dates here. */
  const days = week?.days ?? [];

  const byDay = useMemo<Item[][]>(() => {
    const out: Item[][] = days.map(() => []);
    if (!tz) return out;
    const index = new Map(days.map((d, i) => [d.date, i]));
    // Interviews come with the week; they are the fixed skeleton of the day and
    // are not movable from here.
    days.forEach((d, i) => {
      for (const iv of d.interviews ?? []) {
        const start = minutesOfDay(iv.at, tz);
        if (start === null) continue;
        out[i].push({
          kind: "interview", interview: iv, start,
          // A real appointment is not rounded: it runs as long as it runs.
          duration: iv.duration_minutes ?? null,
          slot: iv.duration_minutes ?? null,
          title: iv.company,
        });
      }
    });
    for (const a of blocks ?? []) {
      if (!a.scheduled_at) continue;
      const localDate = new Intl.DateTimeFormat("en-CA", {
        timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
      }).format(new Date(a.scheduled_at));
      const i = index.get(localDate);
      if (i === undefined) continue; // outside the loaded week
      const start = minutesOfDay(a.scheduled_at, tz);
      if (start === null) continue;
      const est = estOf(a);
      out[i].push({ kind: "block", action: a, start, duration: est, slot: snapDuration(est), title: a.title });
    }
    return out;
  }, [days, blocks, tz]);

  // The visible band stretches to hold whatever is actually there, so an 08:00
  // call or a round running past 18:00 is drawn where it belongs instead of
  // being clamped onto the edge row with a label that contradicts its position.
  const band = useMemo(() => bandFor(byDay.flat().map((i) => ({ start: i.start, duration: i.slot }))), [byDay]);
  const rows = useMemo(() => rowsFor(band), [band]);

  // The grid's cells ARE its day columns: with no days, the time-axis labels
  // are the only children left and they flow across all eight columns, which
  // renders as three rows of stray clock times where a week should be. So the
  // grid is only mounted once there is a week to hang it on — a slow network or
  // a failed planner-week request must not produce that.
  const loading = week === null || blocks === null;
  const empty = !loading && days.length === 0;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      {/* Deliberately --space-page-x (28px), not the site-wide
          --space-row-edge (56px): seven columns plus the tray leave each day
          column at exactly the 108px floor under 56px, so any further content
          tips the grid into horizontal scrolling on a wide screen. */}
      <div className="mx-auto max-w-[1160px] px-[var(--space-page-x)] py-6">
        <div className="flex items-baseline gap-2.5 mb-2.5">
          <span
            className="text-[10.5px] font-extrabold uppercase tracking-[0.13em]"
            style={{ color: "var(--primary)" }}
          >
            {t("scheduleEyebrow")}
          </span>
          <h2 className="text-base font-extrabold" style={{ color: "var(--ink-primary)" }}>
            {week
              ? t(viewingThisWeek ? "scheduleTitle" : "scheduleTitleOther", {
                  week: weekLabel(week.week_start),
                })
              : t("viewSchedule")}
          </h2>
          <span className="text-xs ml-auto" style={{ color: "var(--ink-muted)" }}>
            {t("scheduleHint")}
          </span>
        </div>

        <div className="grid grid-cols-1 min-[861px]:grid-cols-[230px_minmax(0,1fr)] gap-4 items-start">
          <div>
            {anchor && (
              <MiniMonth
                anchor={anchor}
                onAnchor={setMonthAnchor}
                today={todayRef.current}
                currentWeekStart={week?.week_start ?? null}
                onPick={(d) => { setWeekParam(d); setMonthAnchor(d); }}
                onToday={() => { setWeekParam(undefined); setMonthAnchor(null); }}
                viewingThisWeek={viewingThisWeek}
                t={t}
              />
            )}
          <Tray
            items={tray}
            loading={loading}
            onDragStart={setDragId}
            onDragEnd={() => { setDragId(null); setOver(null); }}
            onPick={setPicking}
            t={t}
          />
          </div>

          <div
            className="rounded-[14px] overflow-x-auto"
            style={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              boxShadow: "var(--shadow-btn-rest-soft)",
            }}
          >
            {loading ? (
              <div className="h-[560px] animate-pulse" style={{ background: "var(--muted)" }} aria-hidden />
            ) : empty || !tz ? (
              <p className="p-8 text-sm text-center" style={{ color: "var(--ink-muted)" }}>
                {t("scheduleUnavailable")}
              </p>
            ) : (
            <div
              className="grid"
              style={{
                gridTemplateColumns: `${AXIS_W} repeat(7, minmax(108px, 1fr))`,
                minWidth: GRID_MIN,
              }}
            >
              {/* Header: an empty corner over the axis, then one cell per day */}
              <div />
              {days.map((d, i) => (
                <div
                  key={d.date}
                  className="text-[11.5px] font-bold text-center px-0.5 py-[5px]"
                  style={{
                    color: d.is_today ? "var(--match-good-fg)" : "var(--ink-secondary)",
                    borderBottom: "1px solid var(--border)",
                    background: d.is_rest ? "var(--muted)" : undefined,
                  }}
                >
                  {WEEKDAY_KEYS[i] ? t(WEEKDAY_KEYS[i]) : ""}
                  <span
                    className="block text-sm tabular-nums"
                    style={{ color: d.is_today ? "var(--match-good-fg)" : "var(--ink-primary)" }}
                  >
                    {Number(d.date.slice(8, 10))}
                  </span>
                </div>
              ))}

              {/* Time rows */}
              {rows.map((m) => (
                <RowCells
                  key={m}
                  minutes={m}
                  days={days}
                  byDay={byDay}
                  band={band}
                  over={over}
                  dragging={dragId !== null}
                  onOver={setOver}
                  onDrop={(date, min) => {
                    setOver(null);
                    if (dragId) void place(dragId, date, min);
                    setDragId(null);
                  }}
                  onBlockDragStart={setDragId}
                  onBlockDragEnd={() => { setDragId(null); setOver(null); }}
                  onPick={setPicking}
                  onRemove={(id) => void unplace(id)}
                  t={t}
                />
              ))}

              {/* Day footers: Σ / cap */}
              <div />
              {days.map((d, i) => (
                <DayFoot key={d.date} items={byDay[i]} cap={cap} isRest={d.is_rest} t={t} />
              ))}
            </div>
            )}
          </div>
        </div>
      </div>

      {picking && (
        <SchedulePicker
          action={picking}
          days={days}
          band={band}
          busy={busy}
          onClose={() => setPicking(null)}
          onPlace={async (date, minutes) => {
            await place(picking.id, date, minutes);
            setPicking(null);
          }}
          onRemove={async () => {
            await unplace(picking.id);
            setPicking(null);
          }}
          t={t}
        />
      )}
    </div>
  );
}

/**
 * A month at a glance, used to choose which WEEK the grid shows.
 *
 * Deliberately not a month view of the work itself: the endpoint returns one
 * week at a time, so painting density across a whole month would mean either
 * five more requests or inventing numbers for the weeks not loaded. An empty
 * calendar that navigates honestly beats a full one that guesses — the planner
 * already treats "no data" and "zero" as different claims everywhere else.
 */
function MiniMonth({
  anchor, onAnchor, today, currentWeekStart, onPick, onToday, viewingThisWeek, t,
}: {
  anchor: string;
  onAnchor: (a: string) => void;
  today: string | null;
  currentWeekStart: string | null;
  onPick: (date: string) => void;
  onToday: () => void;
  viewingThisWeek: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  const locale = useLocale();
  const rows = monthGrid(anchor);
  const month = anchor.slice(0, 7);
  // Formatted through UTC on purpose: `anchor` is a bare calendar date, and
  // letting the browser zone read it can name the previous month.
  const label = new Intl.DateTimeFormat(locale, {
    timeZone: "UTC", year: "numeric", month: "long",
  }).format(new Date(`${anchor}T12:00:00Z`));

  return (
    <div
      className="rounded-[14px] px-3 py-3 mb-4"
      style={{ background: "var(--card)", border: "1px solid var(--border)", boxShadow: "var(--shadow-btn-rest-soft)" }}
    >
      <div className="flex items-center justify-between mb-2">
        <button
          type="button"
          className="w-6 h-6 rounded hover:bg-[var(--muted)] text-sm"
          onClick={() => onAnchor(shiftMonth(anchor, -1))}
          aria-label={t("monthPrev")}
        >
          ‹
        </button>
        <span className="text-xs font-semibold" style={{ color: "var(--ink-primary)" }}>{label}</span>
        <button
          type="button"
          className="w-6 h-6 rounded hover:bg-[var(--muted)] text-sm"
          onClick={() => onAnchor(shiftMonth(anchor, 1))}
          aria-label={t("monthNext")}
        >
          ›
        </button>
      </div>

      <div className="grid grid-cols-7 text-center">
        {WEEKDAY_KEYS.map((k) => (
          <span key={k} className="text-[9px] pb-1" style={{ color: "var(--ink-faint)" }}>{t(k)}</span>
        ))}
        {rows.flat().map((d) => {
          const inShownWeek = currentWeekStart !== null && mondayOf(d) === currentWeekStart;
          const isToday = d === today;
          const otherMonth = d.slice(0, 7) !== month;
          return (
            <button
              key={d}
              type="button"
              className="h-6 text-[10.5px] tabular-nums"
              style={{
                background: inShownWeek ? "var(--accent)" : undefined,
                color: isToday
                  ? "var(--match-good-fg)"
                  : otherMonth
                    ? "var(--ink-faint)"
                    : "var(--ink-secondary)",
                fontWeight: isToday ? 700 : undefined,
              }}
              onClick={() => onPick(d)}
              aria-label={t("openWeekOf", { date: d })}
            >
              {Number(d.slice(8, 10))}
            </button>
          );
        })}
      </div>

      {!viewingThisWeek && (
        <button
          type="button"
          className="mt-2 w-full text-[11px] py-1 rounded hover:bg-[var(--muted)]"
          style={{ color: "var(--primary)" }}
          onClick={onToday}
        >
          {t("backToThisWeek")}
        </button>
      )}
    </div>
  );
}

/**
 * Choose a day and a time without a mouse.
 *
 * The mockup has no click path, no keyboard handling and no touch events at
 * all — its only way to place a to-do is HTML5 drag-and-drop, which does not
 * fire on a phone and cannot be reached with a keyboard. Copying it faithfully
 * would have shipped a view a keyboard user cannot operate, so this is the one
 * place the implementation deliberately adds an affordance the design lacks.
 */
function SchedulePicker({
  action, days, band, busy, onClose, onPlace, onRemove, t,
}: {
  action: ActionRead;
  days: { date: string; is_rest: boolean; is_today: boolean }[];
  band: { start: number; end: number };
  busy: boolean;
  onClose: () => void;
  onPlace: (date: string, minutes: number) => void;
  onRemove: () => void;
  t: ReturnType<typeof useTranslations>;
}) {
  // "cancel" lives in the common namespace, not tracker — bound to its own
  // identifier so the key checker can tell which namespace each call belongs to.
  const tc = useTranslations("common");
  const [date, setDate] = useState(days.find((d) => d.is_today)?.date ?? days[0]?.date ?? "");
  const [minutes, setMinutes] = useState(Math.max(band.start, 9 * 60));
  const slots = rowsFor(band);

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-sm">
        <DialogTitle>{t("pickerTitle")}</DialogTitle>
        <DialogDescription>{action.title}</DialogDescription>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {days.map((d, i) => (
            <button
              key={d.date}
              type="button"
              className={optionPillVariants({ selected: d.date === date, className: "!h-7 !px-2.5 !text-xs" })}
              onClick={() => setDate(d.date)}
            >
              {t(WEEKDAY_KEYS[i])} {Number(d.date.slice(8, 10))}
            </button>
          ))}
        </div>

        <label className="mt-3 block text-xs" style={{ color: "var(--ink-muted)" }}>
          {t("pickerTime")}
          <select
            className="mt-1 block w-full h-8 px-2 rounded-md border text-sm"
            style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
          >
            {slots.map((m) => (
              <option key={m} value={m}>{fmtClock(m)}</option>
            ))}
          </select>
        </label>

        <div className="mt-4 flex items-center gap-2">
          <Button size="sm" onClick={() => onPlace(date, minutes)} disabled={busy || !date} loading={busy}>
            {t("pickerConfirm")}
          </Button>
          {action.scheduled_at && (
            <Button size="sm" variant="outline" onClick={onRemove} disabled={busy}>
              {t("pickerRemove")}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>
            {tc("cancel")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RowCells({
  minutes, days, byDay, band, over, dragging, onOver, onDrop,
  onBlockDragStart, onBlockDragEnd, onPick, onRemove, t,
}: {
  minutes: number;
  days: { date: string; is_rest: boolean; is_today: boolean }[];
  byDay: Item[][];
  band: { start: number; end: number };
  over: string | null;
  dragging: boolean;
  onOver: (key: string | null) => void;
  onDrop: (date: string, minutes: number) => void;
  onBlockDragStart: (id: string) => void;
  onBlockDragEnd: () => void;
  onPick: (a: ActionRead) => void;
  onRemove: (id: string) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <>
      <div
        className="text-[10px] text-right pr-1.5 tabular-nums -translate-y-1.5"
        style={{ color: "var(--ink-muted)" }}
      >
        {minutes % 60 === 0 ? fmtClock(minutes) : ""}
      </div>
      {days.map((d, i) => {
        const key = `${d.date}:${minutes}`;
        const isOver = over === key;
        return (
          <div
            key={d.date}
            className="relative"
            style={{
              height: ROW_PX,
              borderBottom: "1px solid var(--border-subtle)",
              borderLeft: "1px solid var(--border-subtle)",
              background: isOver
                ? "var(--accent)"
                : d.is_rest
                  ? "var(--muted)"
                  : undefined,
              boxShadow: isOver ? "inset 0 0 0 2px var(--primary)" : undefined,
              borderRadius: isOver ? 4 : undefined,
              zIndex: isOver ? 2 : undefined,
            }}
            onDragOver={(e) => {
              // Only claim the drop when one of OUR items is in flight;
              // preventDefault on anything else tells the browser this grid
              // accepts files it has no idea what to do with.
              if (!dragging) return;
              e.preventDefault();
              onOver(key);
            }}
            onDragLeave={() => onOver(null)}
            onDrop={(e) => {
              if (!dragging) return;
              e.preventDefault();
              onDrop(d.date, minutes);
            }}
          >
            {byDay[i]
              .filter((it) => it.start >= minutes && it.start < minutes + SLOT)
              .map((it, n) => (
                <Block
                  key={`${it.kind}-${n}`}
                  item={it}
                  band={band}
                  rowStart={minutes}
                  onDragStart={onBlockDragStart}
                  onDragEnd={onBlockDragEnd}
                  onPick={onPick}
                  onRemove={onRemove}
                  t={t}
                />
              ))}
          </div>
        );
      })}
    </>
  );
}

function Block({
  item, band, rowStart, onDragStart, onDragEnd, onPick, onRemove, t,
}: {
  item: Item;
  band: { start: number; end: number };
  rowStart: number;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onPick: (a: ActionRead) => void;
  onRemove: (id: string) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  const geo = geometryFor({ start: item.start, duration: item.slot }, band);
  if (!geo) return null;
  const isInterview = item.kind === "interview";
  // top is measured from the band; the cell it lives in already starts at
  // rowStart, so only the remainder inside this row is offset.
  const top = geo.top - ((rowStart - band.start) / SLOT) * SLOT_H;
  const end = item.slot === null ? null : item.start + item.slot;

  const when = end === null
    ? t("blockTimeUnknownEnd", { start: fmtClock(item.start) })
    : `${fmtClock(item.start)}–${fmtClock(end)}`;

  return (
    <div
      className="absolute rounded-[7px] px-2 py-[3px] text-[11px] leading-[1.35] overflow-hidden group"
      style={{
        left: BLOCK_INSET, right: BLOCK_INSET, top, height: geo.height, zIndex: 3,
        background: isInterview ? "var(--warn-bg)" : "var(--accent)",
        border: `1px solid ${isInterview ? "var(--warn-border)" : "var(--match-good-border)"}`,
        color: "var(--ink-primary)",
        // A solid ring in the card colour, not a shadow: it hides the grid
        // lines running underneath the block.
        boxShadow: "0 0 0 2px var(--card)",
        cursor: isInterview ? "default" : "grab",
      }}
      title={`${item.title} · ${when}`}
      // Interviews are the day's fixed skeleton: they come from the timeline,
      // and moving one here would say the round was rescheduled when it was not.
      draggable={!isInterview}
      onDragStart={() => { if (!isInterview) onDragStart(item.action.id); }}
      onDragEnd={onDragEnd}
    >
      {isInterview ? (
        <b className="block text-[11px] truncate">📌 {item.title}</b>
      ) : (
        <button
          type="button"
          className="block w-full text-left text-[11px] font-bold truncate hover:underline"
          onClick={() => onPick(item.action)}
        >
          {item.title}
        </button>
      )}
      <span style={{ color: "var(--ink-muted)" }}>{when}</span>
      {!isInterview && (
        <button
          type="button"
          className="absolute top-0 right-1 text-[11px] opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
          style={{ color: "var(--ink-muted)" }}
          onClick={() => onRemove(item.action.id)}
          aria-label={t("unscheduleAria", { title: item.title })}
        >
          ✕
        </button>
      )}
    </div>
  );
}

function DayFoot({
  items, cap, isRest, t,
}: {
  items: Item[];
  cap: number;
  isRest: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  // Unknown-length rounds are excluded rather than counted as a slot: a total is
  // a claim about the day, and padding it with a guess makes the claim false.
  const known = items.filter((i) => i.duration !== null);
  const total = known.reduce((s, i) => s + (i.duration ?? 0), 0);
  const unknown = items.length - known.length;
  const over = cap > 0 && total > cap;
  return (
    <div
      className="text-[10.5px] text-center px-0.5 py-[5px] tabular-nums"
      style={{
        color: over ? "var(--danger-fg)" : "var(--ink-muted)",
        fontWeight: over ? 700 : undefined,
        borderLeft: "1px solid var(--border-subtle)",
        // Carries the rest-day tint through the footer row, or a weekend column
        // stops one row short of the bottom and reads as a rendering fault.
        background: isRest ? "var(--muted)" : undefined,
      }}
    >
      {total === 0 && unknown === 0
        ? ""
        : cap > 0
          ? `${fmtMinutes(total)} / ${fmtMinutes(cap)}${unknown ? " +?" : ""}`
          : `${fmtMinutes(total)}${unknown ? " +?" : ""}`}
    </div>
  );
}

function Tray({
  items, loading, onDragStart, onDragEnd, onPick, t,
}: {
  items: ActionRead[] | null;
  loading: boolean;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onPick: (a: ActionRead) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className="min-[861px]:sticky min-[861px]:top-2">
      <div
        className="rounded-[14px] px-[18px] py-4"
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
          boxShadow: "var(--shadow-btn-rest-soft)",
        }}
      >
        <div className="flex items-baseline gap-2.5 mb-1">
          <span
            className="text-[10.5px] font-extrabold uppercase tracking-[0.13em]"
            style={{ color: "var(--primary)" }}
          >
            {t("trayTitle")}
          </span>
          <span className="text-xs ml-auto tabular-nums" style={{ color: "var(--ink-muted)" }}>
            {items ? t("trayCount", { count: items.length }) : ""}
          </span>
        </div>
        {loading ? (
          <div className="h-24 animate-pulse rounded" style={{ background: "var(--muted)" }} aria-hidden />
        ) : items && items.length > 0 ? (
          items.map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-2 px-2.5 py-[7px] my-1.5 rounded-[9px] text-[12.5px] select-none"
              style={{ background: "var(--card)", border: "1px solid var(--border)", cursor: "grab" }}
              draggable
              onDragStart={() => onDragStart(a.id)}
              onDragEnd={onDragEnd}
            >
              {/* A real button, not a div with a key handler: it is reachable by
                  Tab and fires on Enter for free, and rowKeyboard.test.ts forbids
                  the role="button" + onKeyDown shape that stole space bar from an
                  input the last time this was hand-rolled. */}
              <button
                type="button"
                className="truncate text-left hover:underline"
                style={{ color: "var(--ink-secondary)" }}
                onClick={() => onPick(a)}
              >
                {a.title}
              </button>
              <span className="ml-auto text-[10.5px] tabular-nums shrink-0" style={{ color: "var(--ink-muted)" }}>
                ~{estOf(a)}m
              </span>
            </div>
          ))
        ) : (
          <p className="text-xs py-2" style={{ color: "var(--ink-muted)" }}>{t("trayEmpty")}</p>
        )}
        <p className="text-[11.5px] mt-2 leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          {t("trayHint")}
        </p>
      </div>
    </div>
  );
}

/** "Aug 3 – Aug 9" from the server's week_start, without parsing it into a
 *  Date and back through the browser's zone. */
function weekLabel(weekStart: string): string {
  const [, m, d] = weekStart.split("-").map(Number);
  const end = new Date(Date.UTC(2000, m - 1, d + 6));
  return `${m}/${d} – ${end.getUTCMonth() + 1}/${end.getUTCDate()}`;
}
