"use client";

import { useLocale } from "next-intl";
import { useSearchParams } from "next/navigation";
import { usePathname, useRouter } from "@/i18n/navigation";

const LOCALES: { code: "en" | "zh"; label: string }[] = [
  { code: "en", label: "EN" },
  { code: "zh", label: "中文" },
];

export function LanguageSwitcher() {
  const locale = useLocale();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();

  function switchTo(next: "en" | "zh") {
    if (next === locale) return;
    const query = searchParams.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { locale: next });
  }

  return (
    <div className="flex items-center gap-0.5 rounded-lg p-0.5" style={{ background: "var(--muted)" }}>
      {LOCALES.map(({ code, label }) => (
        <button
          key={code}
          type="button"
          onClick={() => switchTo(code)}
          aria-pressed={locale === code}
          className="px-2.5 py-1 rounded-md text-[12px] font-medium transition-colors"
          style={
            locale === code
              ? { background: "#fff", color: "var(--foreground)", boxShadow: "0 1px 2px oklch(0% 0 0 / 0.06)" }
              : { color: "var(--muted-foreground)" }
          }
        >
          {label}
        </button>
      ))}
    </div>
  );
}
