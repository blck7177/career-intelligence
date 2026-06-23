import Link from "next/link";
import { Cpu } from "lucide-react";

const NAV_ITEMS = [
  { href: "/jobs", label: "Jobs" },
  { href: "/workspace", label: "Workspace" },
  { href: "/runs", label: "Activity" },
  { href: "/profile", label: "Profile" },
];

export function Nav() {
  return (
    <nav className="border-b border-zinc-200 bg-white">
      <div className="max-w-5xl mx-auto px-4 flex h-14 items-center gap-6">
        <Link href="/" className="flex items-center gap-2 font-semibold text-sm">
          <Cpu size={16} className="text-zinc-700" />
          <span>Career OpenClaw</span>
        </Link>
        <div className="flex gap-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="px-3 py-1.5 rounded-md text-sm text-zinc-600 hover:text-zinc-900 hover:bg-zinc-50 transition-colors"
            >
              {item.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
