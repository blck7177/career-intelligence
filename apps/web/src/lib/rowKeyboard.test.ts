import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

/**
 * A container that calls itself a button must not also handle keys.
 *
 * `role="button"` + `tabIndex` + an Enter/Space handler makes an element the
 * keyboard target for everything nested inside it, because keydown bubbles:
 *
 *   - a space typed in a nested <input> reaches the container's handler, which
 *     calls preventDefault() — the space never reaches the input, and whatever
 *     the container does on activation happens instead;
 *   - tabbing to a nested <button> and pressing Enter fires the button (via its
 *     synthetic click) AND the container.
 *
 * V7-C2 shipped exactly this on the Applications row and four review lenses
 * found it independently. stopPropagation on each nested control would fix the
 * controls that exist today; not owning the keyboard fixes the ones added
 * later. The working shape is elsewhere in this codebase already: a plain
 * container with onClick, and the TITLE as the button — mouse and keyboard then
 * travel one path (click, bubbling from the real button) with no second handler
 * to keep in sync.
 *
 * There is no jsdom in this repo, so this is a static check. It is deliberately
 * narrow: it does not object to role="button", only to role="button" that also
 * takes keys.
 */

const SRC = join(__dirname, "..");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return full.endsWith(".tsx") ? [full] : [];
  });
}

/** The text of every JSX opening tag, `<` through the matching `>`. Tracks brace
 *  depth and quotes so `onClick={() => f(a > b)}` does not end the tag early. */
export function openingTags(src: string): string[] {
  const out: string[] = [];
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== "<" || !/[A-Za-z]/.test(src[i + 1] ?? "")) continue;
    let depth = 0;
    let quote = "";
    let j = i + 1;
    for (; j < src.length; j++) {
      const c = src[j];
      if (quote) {
        if (c === quote) quote = "";
        continue;
      }
      if (c === '"' || c === "'" || c === "`") quote = c;
      else if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0) break;
    }
    out.push(src.slice(i, j));
    i = j;
  }
  return out;
}

describe("row keyboard ownership", () => {
  it("no element is both role=\"button\" and its own keydown handler", () => {
    const offenders: Record<string, string[]> = {};
    for (const file of walk(SRC)) {
      const bad = openingTags(readFileSync(file, "utf8"))
        .filter((tag) => tag.includes('role="button"') && tag.includes("onKeyDown"))
        .map((tag) => tag.slice(0, 60).replace(/\s+/g, " "));
      if (bad.length) offenders[file.slice(SRC.length + 1)] = bad;
    }
    expect(offenders).toEqual({});
  });
});
