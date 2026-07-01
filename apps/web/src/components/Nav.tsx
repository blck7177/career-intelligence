"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { UserButton } from "@clerk/nextjs";
import { Inbox, Bookmark, Search, FileText } from "lucide-react";
import type { LucideIcon } from "lucide-react";

const NAV_ITEMS: { href: string; key: string; exact: boolean; icon: LucideIcon }[] = [
  { href: "/", key: "inbox", exact: true, icon: Inbox },
  { href: "/jobs", key: "saved", exact: false, icon: Bookmark },
  { href: "/workspace", key: "searches", exact: false, icon: Search },
  { href: "/runs", key: "reports", exact: false, icon: FileText },
];

export function Nav() {
  const t = useTranslations("nav");
  const pathname = usePathname();

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");

  return (
    <aside
      className="w-[260px] shrink-0 flex flex-col h-full bg-white"
      style={{ borderRight: "1px solid var(--sidebar-border)" }}
    >
      {/* Brand */}
      <div className="px-6 pt-7 pb-5">
        <Link href="/" className="flex items-center gap-3.5">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: "var(--primary)" }}
          >
            <Search size={20} color="#fff" strokeWidth={2.2} />
          </div>
          <span className="text-lg font-semibold" style={{ color: "var(--foreground)" }}>
            {t("brand")}
          </span>
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-1">
        {NAV_ITEMS.map(({ href, key, icon: Icon, exact }) => {
          const active = isActive(href, exact);
          return (
            <Link
              key={href}
              href={href}
              className="relative flex items-center gap-4 px-5 py-3.5 rounded-xl mb-1 transition-colors"
              style={{
                background: active ? "var(--sidebar-item-active-bg)" : undefined,
                color: active ? "var(--sidebar-item-active-fg)" : "var(--sidebar-fg)",
                fontWeight: active ? 600 : 400,
                fontSize: "16px",
              }}
            >
              {active && (
                <span
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3.5px] h-6 rounded-r-full"
                  style={{ background: "var(--primary)" }}
                />
              )}
              <Icon
                size={22}
                strokeWidth={active ? 2.3 : 1.8}
                className="shrink-0"
                style={{ color: active ? "var(--primary)" : "oklch(48% 0.008 275)" }}
              />
              <span>{t(key)}</span>
            </Link>
          );
        })}
      </nav>

      {/* Profile footer */}
      <div
        className="px-6 py-5 flex items-center gap-4"
        style={{ borderTop: "1px solid var(--sidebar-border)" }}
      >
        <UserButton
          appearance={{
            elements: {
              avatarBox: "w-11 h-11",
            },
          }}
        />
        <Link href="/profile" className="min-w-0 group">
          <div className="text-[16px] font-medium group-hover:underline" style={{ color: "oklch(22% 0.015 275)" }}>
            {t("profile")}
          </div>
          <div className="text-[13px]" style={{ color: "oklch(48% 0.01 275)" }}>
            {t("editProfile")}
          </div>
        </Link>
      </div>
    </aside>
  );
}
