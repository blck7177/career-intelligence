/**
 * Shared low-saturation color system for anything that visualizes a 0-100
 * candidate/job match score: strong (>=70), partial (50-69), gaps (<50).
 * This is the ONLY place color carries meaning across fit-related UI —
 * everything else (unrelated job/run statuses) keeps using the app-wide
 * --match-* tokens and is untouched by this module.
 *
 * Each band is one low-chroma oklch base color; every other token (track/bg/
 * border) is that same base at a lower alpha composited over the surface,
 * rather than a separate solid pastel, so they can't drift out of sync.
 */

export type Band = "strong" | "partial" | "gaps";

export function bandOf(score: number): Band {
  return score >= 70 ? "strong" : score >= 50 ? "partial" : "gaps";
}

interface BandBase {
  l: number;
  c: number;
  h: number;
  textL: number;
}

const BAND_BASE: Record<Band, BandBase> = {
  strong: { l: 58, c: 0.065, h: 155, textL: 34 },
  partial: { l: 62, c: 0.075, h: 78, textL: 38 },
  gaps: { l: 56, c: 0.075, h: 22, textL: 40 },
};

export interface BandTokens {
  ring: string;
  track: string;
  fg: string;
  bg: string;
  border: string;
}

function oklchA(l: number, c: number, h: number, a: number): string {
  return `oklch(${l}% ${c} ${h} / ${a})`;
}

export const BAND: Record<Band, BandTokens> = Object.fromEntries(
  (Object.keys(BAND_BASE) as Band[]).map((key) => {
    const b = BAND_BASE[key];
    const tokens: BandTokens = {
      ring: oklchA(b.l, b.c, b.h, 0.8),
      track: oklchA(b.l, b.c, b.h, 0.14),
      fg: oklchA(b.textL, b.c, b.h, 1),
      bg: oklchA(b.l, b.c, b.h, 0.1),
      border: oklchA(b.l, b.c, b.h, 0.32),
    };
    return [key, tokens];
  }),
) as Record<Band, BandTokens>;

/** The app's own purple secondary tokens, reused for anything non-status. */
export const THEME_CHIP = "bg-[var(--secondary)] text-[var(--secondary-foreground)]";
