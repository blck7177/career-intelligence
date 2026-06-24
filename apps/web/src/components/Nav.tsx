"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Cpu, LayoutDashboard, Inbox, Search, User, Activity } from "lucide-react";

const PRIMARY_NAV = [
  { href: "/", label: "Command Center", icon: LayoutDashboard, exact: true },
  { href: "/jobs", label: "Role Inbox", icon: Inbox, exact: false },
  { href: "/workspace", label: "Search Setup", icon: Search, exact: false },
  { href: "/profile", label: "Profile", icon: User, exact: false },
];

const SECONDARY_NAV = [
  { href: "/runs", label: "Search Runs", icon: Activity },
];

export function Nav() {
  const pathname = usePathname();

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");

  return (
    <aside
      className="w-56 shrink-0 flex flex-col h-full"
      style={{
        background: "var(--sidebar-bg)",
        borderRight: "1px solid var(--sidebar-border)",
      }}
    >
      {/* Brand */}
      <div
        className="px-4 py-5 shrink-0"
        style={{ borderBottom: "1px solid var(--sidebar-border)" }}
      >
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0 group-hover:bg-indigo-500 transition-colors">
            <Cpu size={14} className="text-white" />
          </div>
          <div>
            <p className="text-xs font-bold text-white leading-tight tracking-wide">
              OpenClaw
            </p>
            <p className="text-[10px] leading-tight" style={{ color: "var(--sidebar-brand-sub)" }}>
              Career Intelligence
            </p>
          </div>
        </Link>
      </div>

      {/* Primary nav */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {PRIMARY_NAV.map(({ href, label, icon: Icon, exact }) => {
          const active = isActive(href, exact);
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors"
              style={
                active
                  ? {
                      background: "var(--sidebar-item-active-bg)",
                      color: "var(--sidebar-item-active-fg)",
                      fontWeight: 500,
                    }
                  : undefined
              }
              onMouseEnter={(e) => {
                if (!active) {
                  (e.currentTarget as HTMLElement).style.background = "var(--sidebar-item-hover)";
                  (e.currentTarget as HTMLElement).style.color = "#ffffff";
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  (e.currentTarget as HTMLElement).style.background = "";
                  (e.currentTarget as HTMLElement).style.color = "";
                }
              }}
            >
              <Icon
                size={15}
                style={{ color: active ? "#ffffff" : "var(--sidebar-fg)", opacity: active ? 1 : 0.6 }}
              />
              <span style={{ color: active ? "#ffffff" : "var(--sidebar-fg)" }}>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Secondary nav */}
      <div
        className="px-2 py-3 shrink-0"
        style={{ borderTop: "1px solid var(--sidebar-border)" }}
      >
        {SECONDARY_NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(href, false);
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-2.5 px-3 py-2 rounded-md text-xs transition-colors"
              style={
                active
                  ? { color: "#ffffff", fontWeight: 500 }
                  : { color: "var(--sidebar-fg)", opacity: 0.5 }
              }
              onMouseEnter={(e) => {
                if (!active) {
                  (e.currentTarget as HTMLElement).style.opacity = "1";
                  (e.currentTarget as HTMLElement).style.background = "var(--sidebar-item-hover)";
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  (e.currentTarget as HTMLElement).style.opacity = "0.5";
                  (e.currentTarget as HTMLElement).style.background = "";
                }
              }}
            >
              <Icon size={13} style={{ color: active ? "#e0e0ff" : "var(--sidebar-fg)" }} />
              <span>{label}</span>
            </Link>
          );
        })}
      </div>
    </aside>
  );
}
