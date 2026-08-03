/**
 * Geometry for the week schedule grid.
 *
 * Pure arithmetic, kept out of the component because the interaction itself
 * cannot be tested here (no jsdom, no testing-library) — so everything that CAN
 * be checked is separated from everything that can only be looked at.
 *
 * The numbers come from the Compass mockup and are load-bearing on each other:
 * SLOT_H must equal the rendered row height or blocks drift away from the grid
 * lines they are supposed to sit on.
 */

/** Minutes per row. */
export const SLOT = 30;
/** Row height in px. Must match the `.slot` height in the grid. */
export const SLOT_H = 34;
/** Default visible band, 09:00–18:00, as minutes from local midnight. */
export const DEFAULT_START = 9 * 60;
export const DEFAULT_END = 18 * 60;
/** Blocks inset from the column edges, so adjacent columns stay readable. */
export const BLOCK_INSET = 3;
/** Trimmed off a block's height to leave a visual seam between stacked blocks. */
export const BLOCK_SEAM = 4;

export interface Placed {
  /** Minutes from local midnight. */
  start: number;
  /** Minutes. Null = the row exists but nobody recorded how long it runs. */
  duration: number | null;
}

/**
 * The visible time band for a week.
 *
 * The mockup hardcodes 09:00–18:00 and clamps anything outside it to the edge
 * row — which draws an 08:00 interview on the 09:00 line while its own label
 * still reads 08:00. That is worse than hiding it: the picture looks right and
 * is not, and a user plans the surrounding hours around it.
 *
 * So the band stretches to contain what is actually there. A week with nothing
 * unusual in it looks exactly like the mockup; a week with an early call or a
 * late round grows a few rows rather than lying about where they sit.
 */
export function bandFor(items: Placed[]): { start: number; end: number } {
  let start = DEFAULT_START;
  let end = DEFAULT_END;
  for (const it of items) {
    if (it.start < start) start = Math.floor(it.start / SLOT) * SLOT;
    const finish = it.start + (it.duration ?? SLOT);
    if (finish > end) end = Math.ceil(finish / SLOT) * SLOT;
  }
  // Clamp to a real day. A malformed instant should not generate 40,000 rows.
  return { start: Math.max(0, start), end: Math.min(24 * 60, Math.max(end, start + SLOT)) };
}

/** Row start times, in minutes from local midnight. */
export function rowsFor(band: { start: number; end: number }): number[] {
  const out: number[] = [];
  for (let m = band.start; m < band.end; m += SLOT) out.push(m);
  return out;
}

/**
 * Where a block sits inside the grid, in px from the top of the band.
 *
 * Returns null when it falls outside — callers render nothing rather than
 * pinning it to an edge. With bandFor above this should not happen for real
 * data, which is the point: if it ever does, something is wrong upstream and
 * silently drawing it in the wrong place would hide that.
 */
export function geometryFor(
  item: Placed,
  band: { start: number; end: number },
): { top: number; height: number } | null {
  if (item.start < band.start || item.start >= band.end) return null;
  const top = ((item.start - band.start) / SLOT) * SLOT_H;
  const minutes = item.duration ?? SLOT;
  // Never taller than the remaining band, or a late block would paint over the
  // day footer below the grid.
  const capped = Math.min(minutes, band.end - item.start);
  const height = Math.max(SLOT_H, (capped / SLOT) * SLOT_H) - BLOCK_SEAM;
  return { top, height };
}

/**
 * How long a to-do occupies when dropped, from its estimate.
 *
 * Rounds to the nearest slot with a one-slot floor, so a 15-minute follow-up
 * still gets something clickable and a 45-minute task takes an hour of the
 * picture — which is the honest reading, since it will run into the next slot.
 */
export function snapDuration(estMinutes: number): number {
  return Math.max(SLOT, Math.round(estMinutes / SLOT) * SLOT);
}

/** Minutes from local midnight for an instant, read in `tz`. */
export function minutesOfDay(iso: string, tz: string): number | null {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hour12: false, hour: "2-digit", minute: "2-digit",
  }).formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)?.value;
  const h = Number(get("hour"));
  const m = Number(get("minute"));
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
  // hour12:false yields 24 for midnight in some engines.
  return (h % 24) * 60 + m;
}

/** "9:30" for a minute offset — the grid's own axis labels and block times. */
export function fmtClock(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

// --- month grid (the week picker) -------------------------------------------

/** Monday of the week `isoDate` falls in. Weeks are Mon..Sun everywhere in the
 *  planner, matching week_start_for on the server. */
export function mondayOf(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  // getUTCDay: 0=Sunday. Shift so Monday is 0.
  t.setUTCDate(t.getUTCDate() - ((t.getUTCDay() + 6) % 7));
  return t.toISOString().slice(0, 10);
}

/**
 * Whole weeks covering the month `anchor` falls in, as Mon..Sun rows.
 *
 * Bare calendar arithmetic in UTC — no timezone involved, so no DST skew and
 * no chance of the browser's zone deciding which month this is. Leading and
 * trailing days from the neighbouring months are included so every row is a
 * real week: the grid's job is to pick a WEEK, and a ragged row would offer
 * days that belong to a week it cannot show.
 */
export function monthGrid(anchor: string): string[][] {
  const [y, m] = anchor.split("-").map(Number);
  const first = `${y}-${String(m).padStart(2, "0")}-01`;
  const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const last = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
  const rows: string[][] = [];
  let cursor = mondayOf(first);
  const stop = mondayOf(last);
  while (true) {
    const [cy, cm, cd] = cursor.split("-").map(Number);
    const row: string[] = [];
    for (let i = 0; i < 7; i++) {
      const t = new Date(Date.UTC(cy, cm - 1, cd + i));
      row.push(t.toISOString().slice(0, 10));
    }
    rows.push(row);
    if (cursor === stop) break;
    const nx = new Date(Date.UTC(cy, cm - 1, cd + 7));
    cursor = nx.toISOString().slice(0, 10);
  }
  return rows;
}

/** Shift a month anchor by whole months, clamping the day so 3/31 → 2/28. */
export function shiftMonth(anchor: string, months: number): string {
  const [y, m, d] = anchor.split("-").map(Number);
  const target = new Date(Date.UTC(y, m - 1 + months, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(d, lastDay));
  return target.toISOString().slice(0, 10);
}

/** A rectangle in viewport coordinates — what getBoundingClientRect returns. */
export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/**
 * Where to put a popover opened from a grid cell.
 *
 * Viewport-fixed rather than absolute inside the cell, because the grid sits in
 * an `overflow-x-auto` wrapper: a cell-relative popover on one of the later
 * columns is clipped by the scroller it lives in, and the last column — Sunday,
 * the one furthest right — is exactly where a week gets planned from.
 *
 * It opens to the RIGHT of the cell and flips to the left only when it would
 * not fit, which keeps it off the slot the user is aiming at. Vertically it
 * hangs from the cell's top and slides up if it would run past the bottom, so
 * a late-afternoon row still shows the whole menu.
 */
export function menuPlacement(
  cell: Rect,
  menu: { width: number; height: number },
  viewport: { width: number; height: number },
  gap = 6,
): { left: number; top: number } {
  const toRight = cell.right + gap;
  const toLeft = cell.left - gap - menu.width;
  const left = toRight + menu.width <= viewport.width - gap
    ? toRight
    : Math.max(gap, toLeft);
  const top = Math.max(gap, Math.min(cell.top, viewport.height - menu.height - gap));
  return { left, top };
}
