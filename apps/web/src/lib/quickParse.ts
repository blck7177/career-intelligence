/**
 * Quick-add parsing: turn one typed line into a to-do's fields.
 *
 * Capture has to cost about two seconds or it doesn't happen — the thought goes
 * to a sticky note instead, and the planner stops describing reality. So the
 * input accepts what someone would actually type ("follow up databricks next
 * tue =15m") rather than making them fill a form.
 *
 * Two rules the whole thing hangs on:
 *
 * 1. **Every match is shown and revocable.** The parse is a guess about intent,
 *    and a silent wrong guess is worse than no parsing at all — the user only
 *    finds out after the to-do is filed on the wrong day. Callers render one chip
 *    per match and can drop any of them, so `parseQuickAdd` reports what it found
 *    with positions rather than quietly rewriting the text.
 *
 * 2. **Dates use the workspace's day, not the browser's.** A due date is the UTC
 *    instant of local midnight in `settings.timezone` — the same contract the
 *    rules engine writes (packages/domain/planner/rules.py local_day_start_utc).
 *    Computing it from the browser's zone would file to-dos a day off for anyone
 *    travelling, and the strip and Today list would disagree about which day it
 *    landed on.
 */

export type QuickAddType = "follow_up" | "networking" | "apply";

export interface QuickAddMatch {
  /** The exact substring matched, so callers can show and strike it. */
  text: string;
  start: number;
  end: number;
}

export interface QuickAddParse {
  /** The line with every accepted match removed — what becomes the title. */
  title: string;
  date?: QuickAddMatch & { /** local calendar date, YYYY-MM-DD */ date: string };
  duration?: QuickAddMatch & { minutes: number };
  type?: QuickAddMatch & { value: QuickAddType };
}

export interface QuickAddOptions {
  /** Which matches to honour; omit to accept all. Callers pass this to undo a chip. */
  accept?: { date?: boolean; duration?: boolean; type?: boolean };
}

// --- day arithmetic in a given timezone -------------------------------------

/** Today's calendar date in `tz`, as YYYY-MM-DD. */
export function localToday(tz: string, now: Date = new Date()): string {
  // en-CA formats as YYYY-MM-DD, which sidesteps hand-rolling the padding.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
}

function addDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  // UTC arithmetic on a bare calendar date: no zone involved, so no DST skew.
  const t = new Date(Date.UTC(y, m - 1, d));
  t.setUTCDate(t.getUTCDate() + days);
  return t.toISOString().slice(0, 10);
}

/** 0=Monday … 6=Sunday for a bare calendar date. */
function weekdayOf(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

/**
 * The UTC instant of local midnight on `isoDate` in `tz` — the exact encoding
 * the backend uses for due_at, found by probing rather than by hardcoding
 * offsets (which would be wrong across DST and for half-hour zones).
 */
export function localMidnightUtc(isoDate: string, tz: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const guess = Date.UTC(y, m - 1, d);
  // How far the guess is from the target, measured in the target zone.
  const shift = (ms: number): number => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hour12: false,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(ms));
    const get = (t: string) => Number(parts.find((p) => p.type === t)!.value);
    const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"),
                           get("hour") % 24, get("minute"), get("second"));
    return asUtc - ms;
  };
  // One correction lands it; a second settles the case where the correction
  // itself crossed a DST boundary.
  let ms = guess - shift(guess);
  ms = guess - shift(ms);
  return new Date(ms).toISOString();
}

// --- patterns ---------------------------------------------------------------

const WEEKDAYS: Record<string, number> = {
  mon: 0, monday: 0, tue: 1, tues: 1, tuesday: 1, wed: 2, weds: 2, wednesday: 2,
  thu: 3, thur: 3, thurs: 3, thursday: 3, fri: 4, friday: 4,
  sat: 5, saturday: 5, sun: 6, sunday: 6,
  一: 0, 二: 1, 三: 2, 四: 3, 五: 4, 六: 5, 日: 6, 天: 6,
};

// Longest-first so "next tuesday" wins over "tue", and 下周三 over 周三.
const DATE_PATTERNS: Array<{ re: RegExp; resolve: (m: RegExpMatchArray, today: string) => string }> = [
  { re: /\b(today)\b/i, resolve: (_m, today) => today },
  { re: /\b(tomorrow|tmr|tmrw)\b/i, resolve: (_m, today) => addDays(today, 1) },
  { re: /\bday after tomorrow\b/i, resolve: (_m, today) => addDays(today, 2) },
  { re: /(今天|今日)/, resolve: (_m, today) => today },
  { re: /(明天|明日)/, resolve: (_m, today) => addDays(today, 1) },
  { re: /(后天)/, resolve: (_m, today) => addDays(today, 2) },
  {
    re: /下(?:个)?周([一二三四五六日天])/,
    resolve: (m, today) => nextWeekday(today, WEEKDAYS[m[1]], true),
  },
  {
    re: /(?:这|本)?周([一二三四五六日天])/,
    resolve: (m, today) => nextWeekday(today, WEEKDAYS[m[1]], false),
  },
  {
    re: /\bnext\s+(mon|monday|tue|tues|tuesday|wed|weds|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)\b/i,
    resolve: (m, today) => nextWeekday(today, WEEKDAYS[m[1].toLowerCase()], true),
  },
  {
    re: /\b(mon|monday|tue|tues|tuesday|wed|weds|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)\b/i,
    resolve: (m, today) => nextWeekday(today, WEEKDAYS[m[1].toLowerCase()], false),
  },
];

/**
 * Resolve a weekday name to a date.
 *
 * A bare name ("friday", 周五) means the soonest one still ahead — never today,
 * since a to-do for right now would just be typed without a date.
 *
 * "next X" / 下周X means that weekday in the NEXT CALENDAR WEEK, not "one more
 * week past the soonest one". Typed on a Wednesday, 下周二 is the Tuesday of the
 * week that starts next Monday — which is also the soonest Tuesday ahead, so the
 * two spellings agree here; typed on a Monday they differ (tomorrow vs. eight
 * days out). Treating it as a +7 offset instead gave 下周二 a date two weeks out,
 * which is not what either language means.
 */
function nextWeekday(today: string, target: number, explicitNext: boolean): string {
  const cur = weekdayOf(today);
  if (explicitNext) {
    const thisMonday = addDays(today, -cur);
    return addDays(thisMonday, 7 + target);
  }
  const delta = (target - cur + 7) % 7;
  return addDays(today, delta === 0 ? 7 : delta);
}

const DURATION_PATTERNS: Array<{ re: RegExp; minutes: (m: RegExpMatchArray) => number }> = [
  { re: /=(\d+)\s*h(?:rs?|ours?)?\b/i, minutes: (m) => Number(m[1]) * 60 },
  { re: /=(\d+)\s*m(?:in(?:s|utes?)?)?\b/i, minutes: (m) => Number(m[1]) },
  { re: /=(\d+)\b/, minutes: (m) => Number(m[1]) },
  { re: /(\d+)\s*小时/, minutes: (m) => Number(m[1]) * 60 },
  { re: /(\d+)\s*分钟/, minutes: (m) => Number(m[1]) },
];

const TYPE_PATTERNS: Array<{ re: RegExp; value: QuickAddType }> = [
  { re: /\bfollow[\s-]?up\b/i, value: "follow_up" },
  { re: /(跟进|催一下)/, value: "follow_up" },
  { re: /\b(outreach|networking|reach out|coffee chat)\b/i, value: "networking" },
  { re: /(内推|触达|约聊)/, value: "networking" },
  { re: /\bappl(?:y|ication)\b/i, value: "apply" },
  { re: /(投递|去投)/, value: "apply" },
];

// est_minutes bounds mirror ActionCreate (ge=5, le=480); a value outside them
// would 422, so an out-of-range duration is treated as not-a-duration and left
// in the title where the user can see it.
const EST_MIN = 5;
const EST_MAX = 480;

function firstMatch<T>(
  text: string,
  patterns: Array<{ re: RegExp }>,
  build: (m: RegExpMatchArray, i: number) => T | null,
): T | null {
  for (let i = 0; i < patterns.length; i++) {
    const m = text.match(patterns[i].re);
    if (m && m.index !== undefined) {
      const built = build(m, i);
      if (built !== null) return built;
    }
  }
  return null;
}

/**
 * Parse one quick-add line. Never throws; an unparseable line simply yields a
 * title and no matches.
 */
export function parseQuickAdd(
  raw: string,
  /** The workspace's zone. Pass null when it isn't known yet (or isn't
   *  available, as in the application detail pane): dates are then left in the
   *  title rather than resolved against a guessed zone, which would file the
   *  to-do a day off. Types and durations need no zone. */
  tz: string | null,
  opts: QuickAddOptions = {},
  now: Date = new Date(),
): QuickAddParse {
  const accept = { date: tz !== null, duration: true, type: true, ...opts.accept };
  const today = tz ? localToday(tz, now) : "";

  const date = accept.date && tz
    ? firstMatch(raw, DATE_PATTERNS, (m, i) => ({
        text: m[0], start: m.index!, end: m.index! + m[0].length,
        date: DATE_PATTERNS[i].resolve(m, today),
      }))
    : null;

  const duration = accept.duration
    ? firstMatch(raw, DURATION_PATTERNS, (m, i) => {
        const minutes = DURATION_PATTERNS[i].minutes(m);
        if (!Number.isFinite(minutes) || minutes < EST_MIN || minutes > EST_MAX) return null;
        return { text: m[0], start: m.index!, end: m.index! + m[0].length, minutes };
      })
    : null;

  const type = accept.type
    ? firstMatch(raw, TYPE_PATTERNS, (m, i) => ({
        text: m[0], start: m.index!, end: m.index! + m[0].length,
        value: TYPE_PATTERNS[i].value,
      }))
    : null;

  // Strip only the date and duration: they are pure metadata. The type keyword
  // is usually the verb ("follow up databricks") and removing it would leave a
  // title that no longer says what to do.
  const cuts = [date, duration].filter(Boolean) as QuickAddMatch[];
  let title = raw;
  for (const c of cuts.sort((a, b) => b.start - a.start)) {
    title = title.slice(0, c.start) + title.slice(c.end);
  }
  title = title.replace(/\s{2,}/g, " ").trim();

  return {
    title,
    ...(date ? { date } : {}),
    ...(duration ? { duration } : {}),
    ...(type ? { type } : {}),
  };
}

/** The due_at to send for a parsed date, in the backend's encoding. */
export function dueAtFor(parse: QuickAddParse, tz: string | null): string | undefined {
  return parse.date && tz ? localMidnightUtc(parse.date.date, tz) : undefined;
}
