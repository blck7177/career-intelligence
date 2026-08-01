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
/** Keys a file references, resolved per translator variable.
 *
 *  The first version keyed off "how many distinct namespaces does this file
 *  declare" and returned nothing when the answer was more than one. That
 *  silently exempted six files and ~220 t() calls — including every page that
 *  mixes its own namespace with `common` — which is the same shape of hole the
 *  test was written to close, one level up. Binding each translator to its
 *  variable (`const t = useTranslations("jobs")`, `const tCommon =
 *  useTranslations("common")`) resolves them exactly, so no file needs an
 *  exemption. `analysable` is false only when a translator cannot be tied to a
 *  name at all, and that is asserted on rather than skipped. */
function usedKeys(src: string): { keys: string[]; analysable: boolean } {
  const declared = [...src.matchAll(/useTranslations\("([^"]+)"\)/g)].map((m) => m[1]);
  if (declared.length === 0) return { keys: [], analysable: true };

  const byVar = new Map<string, string>();
  let ambiguous = false;
  for (const m of src.matchAll(/(?:const|let|var)\s+(\w+)\s*=\s*useTranslations\("([^"]+)"\)/g)) {
    const [, name, ns] = m;
    // The same identifier bound to two namespaces in one file cannot be
    // resolved by name — a component and its sibling would both call `t`.
    if (byVar.has(name) && byVar.get(name) !== ns) ambiguous = true;
    byVar.set(name, ns);
  }
  // Every declaration has to have been bound to a plain identifier; an inline
  // useTranslations("x")("key") leaves calls with no name to attribute.
  const bound = [...src.matchAll(/(?:const|let|var)\s+\w+\s*=\s*useTranslations\("([^"]+)"\)/g)].length;
  if (ambiguous || bound !== declared.length) return { keys: [], analysable: false };

  const keys: string[] = [];
  for (const [name, ns] of byVar) {
    for (const call of src.matchAll(new RegExp(`\\b${name}\\(([^;]*?)\\)`, "g"))) {
      // Only the first argument names the key; the second is the interpolation
      // object, whose quoted values are not keys.
      const firstArg = call[1].split(/,\s*\{/)[0];
      for (const lit of firstArg.matchAll(/(={2,3}\s*|!={1,2}\s*)?"([a-zA-Z][a-zA-Z0-9_.]*)"/g)) {
        // Skip comparison operands: `t(choice === "today" ? "a" : "b")` names two
        // keys, not three.
        if (lit[1]) continue;
        keys.push(`${ns}.${lit[2]}`);
      }
    }
  }
  return { keys, analysable: true };
}

describe("translation keys", () => {
  const enKeys = flatten(en as Record<string, unknown>);

  it("every key used in a component exists in en.json", () => {
    const missing: Record<string, string[]> = {};
    for (const file of walk(SRC)) {
      if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
      const bad = [...new Set(usedKeys(readFileSync(file, "utf8")).keys)].filter(
        (k) => !enKeys.has(k),
      );
      if (bad.length) missing[file.slice(SRC.length + 1)] = bad;
    }
    expect(missing).toEqual({});
  });

  it("no file opts itself out by being unreadable", () => {
    // The check above can only fail for files it can parse. A file it cannot
    // parse looks identical to a file with no mistakes, which is how the
    // previous version exempted six files without anyone noticing. Make that
    // state loud instead: if this fails, either name the translator or teach
    // usedKeys the new shape — do not let it pass silently.
    const unreadable = walk(SRC)
      .filter((f) => !f.endsWith(".test.ts") && !f.endsWith(".test.tsx"))
      .filter((f) => !usedKeys(readFileSync(f, "utf8")).analysable)
      .map((f) => f.slice(SRC.length + 1));
    expect(unreadable).toEqual([]);
  });

  it("en and zh hold the same keys", () => {
    const zhKeys = flatten(zh as Record<string, unknown>);
    expect({
      enOnly: [...enKeys].filter((k) => !zhKeys.has(k)),
      zhOnly: [...zhKeys].filter((k) => !enKeys.has(k)),
    }).toEqual({ enOnly: [], zhOnly: [] });
  });
});
