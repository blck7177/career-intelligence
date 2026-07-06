"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { UserButton } from "@clerk/nextjs";
import { Inbox, Bookmark, Search, FileText } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useApiToken } from "@/hooks/useApiToken";
import { useCountUp } from "@/hooks/useCountUp";
import { listJobs, listRuns } from "@/api/client";

type BadgeType = "urgent" | "neutral" | "none";

function NavBadgeCount({ count, urgent }: { count: number; urgent: boolean }) {
  const animated = useCountUp(count);
  return (
    <span
      className="text-xs font-bold rounded-full px-2 py-[3px] min-w-[20px] text-center tabular-nums"
      style={{
        background: urgent ? "var(--primary)" : "var(--muted)",
        color: urgent ? "#fff" : "var(--muted-foreground)",
      }}
    >
      {animated}
    </span>
  );
}

const NAV_ITEMS: { href: string; key: string; exact: boolean; icon: LucideIcon; badgeType: BadgeType }[] = [
  { href: "/", key: "inbox", exact: true, icon: Inbox, badgeType: "urgent" },
  { href: "/jobs", key: "saved", exact: false, icon: Bookmark, badgeType: "neutral" },
  { href: "/workspace", key: "searches", exact: false, icon: Search, badgeType: "none" },
  { href: "/runs", key: "reports", exact: false, icon: FileText, badgeType: "urgent" },
];

export function Nav() {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const getToken = useApiToken();

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");

  const activeItem = NAV_ITEMS.find((item) => isActive(item.href, item.exact)) ?? NAV_ITEMS[0];

  // Counts behind the nav badges — "inbox" mirrors the dashboard's own
  // unreviewedCount (status === "discovered"), "saved" is the total job
  // count, "reports" is runs still running or awaiting review.
  const [counts, setCounts] = useState<Partial<Record<string, number>>>({});

  const loadCounts = useCallback(() => {
    getToken().then((token) => {
      Promise.all([
        listJobs({ status: "discovered", limit: 1 }, token).catch(() => null),
        listJobs({ limit: 1 }, token).catch(() => null),
        listRuns(token).catch(() => null),
      ]).then(([discovered, all, runs]) => {
        setCounts({
          inbox: discovered?.total ?? 0,
          saved: all?.total ?? 0,
          reports: runs
            ? runs.items.filter((r) => r.status === "running" || r.status === "needs_review").length
            : 0,
        });
      });
    });
  }, [getToken]);

  // Refetch on every client-side navigation so badges don't go stale while
  // the layout (and this component) stays mounted across route changes.
  useEffect(() => {
    loadCounts();
  }, [loadCounts, pathname]);

  // Sliding active highlight — measures the active Link's box instead of a
  // Framer Motion layoutId, so switching tabs doesn't need a new dependency.
  const itemRefs = useRef<Partial<Record<string, HTMLAnchorElement | null>>>({});
  const [highlight, setHighlight] = useState<{ top: number; height: number } | null>(null);
  const [animateHighlight, setAnimateHighlight] = useState(false);

  useLayoutEffect(() => {
    const el = itemRefs.current[activeItem.href];
    if (el) setHighlight({ top: el.offsetTop, height: el.offsetHeight });
    const raf = requestAnimationFrame(() => setAnimateHighlight(true));
    return () => cancelAnimationFrame(raf);
  }, [activeItem.href]);

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

      {/* Nav — only 4 top-level destinations, full-height rail: sized as a
          confident primary nav (~56px rows) rather than a dense file tree. */}
      <nav className="relative flex-1 px-3 pt-0.5 pb-2.5">
        <div
          className="absolute left-3 right-3 rounded-[14px] pointer-events-none"
          style={{
            top: highlight?.top ?? 0,
            height: highlight?.height ?? 0,
            opacity: highlight ? 1 : 0,
            background: "var(--sidebar-item-active-bg)",
            transition: animateHighlight
              ? "top 0.32s cubic-bezier(0.34, 1.1, 0.4, 1), height 0.32s cubic-bezier(0.34, 1.1, 0.4, 1)"
              : "none",
          }}
        />
        {NAV_ITEMS.map(({ href, key, icon: Icon, exact, badgeType }) => {
          const active = isActive(href, exact);
          const badgeCount = counts[key] ?? 0;
          return (
            <Link
              key={href}
              href={href}
              ref={(el) => {
                itemRefs.current[href] = el;
              }}
              className="relative z-[1] flex items-center gap-4 px-5 py-[17px] rounded-[14px] mb-1.5"
              style={{
                color: active ? "var(--sidebar-item-active-fg)" : "var(--sidebar-fg)",
                fontWeight: active ? 680 : 400,
                fontSize: "16px",
              }}
            >
              {active && (
                <span
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3.5px] h-[26px] rounded-r-full"
                  style={{ background: "var(--primary)" }}
                />
              )}
              <Icon
                size={23}
                strokeWidth={active ? 2.4 : 1.9}
                className="shrink-0"
                style={{ color: active ? "var(--primary)" : "var(--ink-muted)" }}
              />
              <span className="flex-1">{t(key)}</span>
              {badgeType !== "none" && badgeCount > 0 && (
                <NavBadgeCount count={badgeCount} urgent={badgeType === "urgent"} />
              )}
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
          <div className="text-[16px] font-medium group-hover:underline" style={{ color: "var(--ink-primary)" }}>
            {t("profile")}
          </div>
          <div className="text-[13px]" style={{ color: "var(--ink-muted)" }}>
            {t("editProfile")}
          </div>
        </Link>
      </div>
    </aside>
  );
}
