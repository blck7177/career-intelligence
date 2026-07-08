"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { UserButton } from "@clerk/nextjs";
import { Inbox, Bookmark, Search, FileText, Menu, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useApiToken } from "@/hooks/useApiToken";
import { useCountUp } from "@/hooks/useCountUp";
import { listJobs, listRuns } from "@/api/client";
import { cn } from "@/lib/utils";
import { Sheet, SheetTrigger, SheetContent } from "@/components/ui/sheet";
import { Tooltip } from "@/components/ui/tooltip";
import { buttonVariants } from "@/components/ui/button-variants";
import { StartRunButton } from "@/app/[locale]/runs/StartRunButton";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

type BadgeType = "urgent" | "neutral" | "none";
type ContextAction = "search" | "run" | "none";

function NavBadgeCount({ count, urgent }: { count: number; urgent: boolean }) {
  const animated = useCountUp(count);
  return (
    <span
      className="text-2xs font-bold rounded-full px-2 py-[3px] min-w-[20px] text-center tabular-nums"
      style={{
        background: urgent ? "var(--primary)" : "#fff",
        color: urgent ? "#fff" : "var(--muted-foreground)",
        border: urgent ? "none" : "1px solid var(--border)",
      }}
    >
      {animated}
    </span>
  );
}

const NAV_ITEMS: { href: string; key: string; exact: boolean; icon: LucideIcon; badgeType: BadgeType; action: ContextAction }[] = [
  { href: "/", key: "inbox", exact: true, icon: Inbox, badgeType: "urgent", action: "search" },
  { href: "/jobs", key: "saved", exact: false, icon: Bookmark, badgeType: "neutral", action: "search" },
  { href: "/workspace", key: "searches", exact: false, icon: Search, badgeType: "none", action: "none" },
  { href: "/runs", key: "reports", exact: false, icon: FileText, badgeType: "urgent", action: "run" },
];

/**
 * Unified top bar — replaces the old left sidebar (Nav.tsx) *and* every
 * page's own h-14 title header. The right-side action slot is derived from
 * the active nav item (search/run/none) instead of being passed in per page,
 * since section -> action is a fixed 1:1 mapping (see NAV_ITEMS.action).
 */
export function TopBar() {
  const t = useTranslations("nav");
  const tHome = useTranslations("home");
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

  // Phone-width drawer open state — controlled so it can be force-closed on
  // navigation (see effect below), not just by its own trigger/backdrop.
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  function contextAction(compact?: boolean) {
    if (activeItem.action === "none") return null;
    if (activeItem.action === "run") return <StartRunButton />;
    return (
      <Link href="/workspace" className={buttonVariants({ size: compact ? "sm" : "md", className: "shrink-0 gap-2" })}>
        <svg width="12" height="12" viewBox="0 0 12 12">
          <line x1="6" y1="1" x2="6" y2="11" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="1" y1="6" x2="11" y2="6" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
        {tHome("newSearch")}
      </Link>
    );
  }

  return (
    <>
      {/* Tablet/desktop bar — sm and up. All 4 destinations shown with
          icon+label+badge and a sliding underline on the active one (reuses
          the same visual language as the app's Tabs component). Hidden
          entirely below sm: see the drawer variant underneath for phone
          widths. */}
      <header
        className="hidden sm:flex items-center gap-2 h-14 px-5 shrink-0 bg-[var(--muted)]"
        style={{ borderBottom: "1px solid var(--sidebar-border)" }}
      >
        <Link href="/" className="flex items-center gap-2.5 shrink-0 pr-2">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: "var(--primary)" }}>
            <Search size={15} color="#fff" strokeWidth={2.2} />
          </div>
          <span className="hidden lg:inline text-base font-semibold" style={{ color: "var(--foreground)" }}>
            {t("brand")}
          </span>
        </Link>

        <nav className="flex items-center h-full gap-1">
          {NAV_ITEMS.map(({ href, key, icon: Icon, exact, badgeType }) => {
            const active = isActive(href, exact);
            const badgeCount = counts[key] ?? 0;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 h-10 px-3.5 rounded-lg text-sm font-medium shrink-0 transition-colors duration-150",
                  active
                    ? "bg-white text-[var(--sidebar-item-active-fg)] font-semibold"
                    : "text-[var(--sidebar-fg)] hover:bg-white hover:text-[var(--ink-primary)]",
                )}
              >
                <Icon size={18} strokeWidth={active ? 2.3 : 1.9} className="shrink-0" />
                <span>{t(key)}</span>
                {badgeType !== "none" && badgeCount > 0 && <NavBadgeCount count={badgeCount} urgent={badgeType === "urgent"} />}
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />

        <div className="flex items-center gap-3 shrink-0">
          {contextAction()}
          <Suspense fallback={null}>
            <LanguageSwitcher />
          </Suspense>
          <Tooltip content={t("editProfile")}>
            <Link
              href="/profile"
              aria-label={t("profile")}
              className="flex items-center justify-center w-8 h-8 rounded-full transition-colors hover:bg-white"
              style={{ color: "var(--ink-muted)" }}
            >
              <UserRound size={17} />
            </Link>
          </Tooltip>
          <UserButton appearance={{ elements: { avatarBox: "w-8 h-8" } }} />
        </div>
      </header>

      {/* Phone-width bar — below sm: hamburger + slide-out drawer (Base UI
          Dialog underneath the shared Sheet primitive: backdrop, focus-trap,
          and portal come for free), brand centered, contextual action
          dropped (too cramped at this width — reachable from within the
          section itself, e.g. the wizard's own Continue button). */}
      <div
        className="sm:hidden flex items-center justify-between h-14 px-4 shrink-0 bg-[var(--muted)]"
        style={{ borderBottom: "1px solid var(--sidebar-border)" }}
      >
        <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
          <SheetTrigger
            aria-label={t("openMenu")}
            className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ border: "1px solid var(--sidebar-border)" }}
          >
            <Menu size={19} style={{ color: "var(--sidebar-fg)" }} />
          </SheetTrigger>
          <SheetContent side="left" aria-label={t("brand")} className="max-w-[280px] flex flex-col">
            <div className="pb-5 flex items-center">
              <Link href="/" className="flex items-center gap-3.5" onClick={() => setDrawerOpen(false)}>
                <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: "var(--primary)" }}>
                  <Search size={20} color="#fff" strokeWidth={2.2} />
                </div>
                <span className="text-lg font-semibold" style={{ color: "var(--foreground)" }}>
                  {t("brand")}
                </span>
              </Link>
            </div>

            <nav className="flex flex-col flex-1 -mx-1">
              {NAV_ITEMS.map(({ href, key, icon: Icon, exact, badgeType }) => {
                const active = isActive(href, exact);
                const badgeCount = counts[key] ?? 0;
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setDrawerOpen(false)}
                    className={cn(
                      "flex items-center gap-4 px-5 py-[17px] rounded-[14px] mb-3 text-lg",
                      active ? "text-[var(--primary)] font-semibold" : "text-[var(--sidebar-fg)] font-medium hover:bg-[var(--sidebar-item-hover)]",
                    )}
                    style={active ? { background: "var(--sidebar-item-active-bg)" } : undefined}
                  >
                    <Icon size={22} strokeWidth={active ? 2.4 : 1.9} className="shrink-0" />
                    <span className="flex-1">{t(key)}</span>
                    {badgeType !== "none" && badgeCount > 0 && <NavBadgeCount count={badgeCount} urgent={badgeType === "urgent"} />}
                  </Link>
                );
              })}
            </nav>

            <div className="pt-5 flex items-center gap-4" style={{ borderTop: "1px solid var(--sidebar-border)" }}>
              <UserButton appearance={{ elements: { avatarBox: "w-11 h-11" } }} />
              <Link href="/profile" className="min-w-0 group" onClick={() => setDrawerOpen(false)}>
                <div className="text-base font-medium group-hover:underline" style={{ color: "var(--ink-primary)" }}>
                  {t("profile")}
                </div>
                <div className="text-sm" style={{ color: "var(--ink-muted)" }}>
                  {t("editProfile")}
                </div>
              </Link>
            </div>
          </SheetContent>
        </Sheet>

        <Link href="/" className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" style={{ background: "var(--primary)" }}>
            <Search size={13} color="#fff" strokeWidth={2.2} />
          </div>
          <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {t("brand")}
          </span>
        </Link>

        <UserButton appearance={{ elements: { avatarBox: "w-8 h-8" } }} />
      </div>
    </>
  );
}
