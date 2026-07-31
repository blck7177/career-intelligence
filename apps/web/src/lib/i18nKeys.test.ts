import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import en from "../../messages/en.json";
import zh from "../../messages/zh.json";

/**
 * Every translation key a component asks for must exist.
 *
 * next-intl renders a missing key as its own path ("tracker.deferToFit") and
 * carries on, so the failure is a visible string in the UI and nothing else:
 * `tsc` is happy (the key is a plain string), the en/zh parity check is happy
 * (it compares the two files to each other, never to the code), and the unit
 * tests never render. V6 shipped exactly that — a working button's label was
 * renamed to a key that did not exist, and four gates passed.
 */

const SRC = join(__dirname, "..");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return full.endsWith(".tsx") || full.endsWith(".ts") ? [full] : [];
  });
}

function flatten(obj: Record<string, unknown>, prefix = ""): Set<string> {
  const out = new Set<string>();
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const nested of flatten(v as Record<string, unknown>, `${prefix}${k}.`)) out.add(nested);
    } else {
      out.add(`${prefix}${k}`);
    }
  }
  return out;
}

/** Keys referenced from a file, with the namespace its useTranslations declares.
 *  Picks up string literals anywhere inside a t(...) call, so the ternary form
 *  `t(cond ? "a" : "b")` is covered — that is the shape that hid one of the two
 *  bugs this test exists for. */
function usedKeys(src: string): string[] {
  // A file may call useTranslations several times (a component plus its
  // sub-components). One namespace across all of them is the case we can read;
  // more than one and we cannot tell which call a given t() belongs to.
  // Skipping quietly is how the first version of this test missed the very bug
  // it was written for, so the distinct-count is what decides, not the raw one.
  const ns = [...new Set([...src.matchAll(/useTranslations\("([^"]+)"\)/g)].map((m) => m[1]))];
  if (ns.length !== 1) return [];
  const keys: string[] = [];
  for (const call of src.matchAll(/\bt\(([^;]*?)\)/g)) {
    // Only the first argument names the key; the second is the interpolation
    // object, whose quoted values are not keys.
    const firstArg = call[1].split(/,\s*\{/)[0];
    for (const lit of firstArg.matchAll(/(={2,3}\s*|!={1,2}\s*)?"([a-zA-Z][a-zA-Z0-9_.]*)"/g)) {
      // Skip comparison operands: `t(choice === "today" ? "a" : "b")` names two
      // keys, not three.
      if (lit[1]) continue;
      keys.push(`${ns[0]}.${lit[2]}`);
    }
  }
  return keys;
}

describe("translation keys", () => {
  const enKeys = flatten(en as Record<string, unknown>);

  it("every key used in a component exists in en.json", () => {
    const missing: Record<string, string[]> = {};
    for (const file of walk(SRC)) {
      if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
      const bad = [...new Set(usedKeys(readFileSync(file, "utf8")))].filter(
        (k) => !enKeys.has(k),
      );
      if (bad.length) missing[file.slice(SRC.length + 1)] = bad;
    }
    expect(missing).toEqual({});
  });

  it("en and zh hold the same keys", () => {
    const zhKeys = flatten(zh as Record<string, unknown>);
    expect({
      enOnly: [...enKeys].filter((k) => !zhKeys.has(k)),
      zhOnly: [...zhKeys].filter((k) => !enKeys.has(k)),
    }).toEqual({ enOnly: [], zhOnly: [] });
  });
});
