"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";

const NAV_ITEMS = [
  {
    href: "/",
    label: "Inbox",
    exact: true,
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <rect x="1.5" y="3" width="13" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
        <path d="M1.5 7h4l2 2 2-2h4" stroke="currentColor" strokeWidth="1.3" />
      </svg>
    ),
  },
  {
    href: "/jobs",
    label: "Saved",
    exact: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path d="M3 2h10a1 1 0 0 1 1 1v11l-6-3-6 3V3a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    href: "/workspace",
    label: "Searches",
    exact: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="6.5" cy="6.5" r="4" stroke="currentColor" strokeWidth="1.3" />
        <line x1="9.8" y1="9.8" x2="13.5" y2="13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/runs",
    label: "Reports",
    exact: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <rect x="2.5" y="1.5" width="11" height="13" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
        <line x1="5" y1="6" x2="11" y2="6" stroke="currentColor" strokeWidth="1.1" />
        <line x1="5" y1="8.5" x2="11" y2="8.5" stroke="currentColor" strokeWidth="1.1" />
        <line x1="5" y1="11" x2="8.5" y2="11" stroke="currentColor" strokeWidth="1.1" />
      </svg>
    ),
  },
];

export function Nav() {
  const pathname = usePathname();

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");

  return (
    <aside
      className="w-[216px] shrink-0 flex flex-col h-full bg-white"
      style={{ borderRight: "1px solid var(--sidebar-border)" }}
    >
      {/* Brand */}
      <div className="px-[18px] pt-5 pb-2.5">
        <Link href="/" className="flex items-center gap-[9px]">
          <div
            className="w-7 h-7 rounded-[7px] flex items-center justify-center shrink-0"
            style={{ background: "var(--primary)" }}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" style={{ color: "#fff" }}>
              <circle cx="6.5" cy="6.5" r="4" stroke="currentColor" strokeWidth="1.6" fill="none" />
              <line x1="9.8" y1="9.8" x2="13.5" y2="13.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </div>
          <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            Career Agent
          </span>
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2.5 py-1.5">
        {NAV_ITEMS.map(({ href, label, icon, exact }) => {
          const active = isActive(href, exact);
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] mb-0.5 transition-colors"
              style={{
                background: active ? "var(--sidebar-item-active-bg)" : undefined,
                color: active ? "var(--sidebar-item-active-fg)" : "var(--sidebar-fg)",
                fontWeight: active ? 500 : 400,
                fontSize: "13.5px",
              }}
            >
              <span className="shrink-0" style={{ color: active ? "var(--sidebar-item-active-fg)" : "oklch(62% 0.008 275)" }}>
                {icon}
              </span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Profile footer */}
      <div
        className="px-[18px] py-3.5 flex items-center gap-2.5"
        style={{ borderTop: "1px solid var(--sidebar-border)" }}
      >
        <UserButton
          appearance={{
            elements: {
              avatarBox: "w-7 h-7",
            },
          }}
        />
        <Link href="/profile" className="min-w-0 group">
          <div className="text-[13px] font-medium group-hover:underline" style={{ color: "oklch(22% 0.015 275)" }}>
            Profile
          </div>
          <div className="text-[11.5px]" style={{ color: "oklch(60% 0.01 275)" }}>
            Edit profile
          </div>
        </Link>
      </div>
    </aside>
  );
}
