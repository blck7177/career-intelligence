import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function statusColor(status: string | null | undefined): string {
  if (!status) return "text-muted-foreground";
  if (status === "succeeded") return "text-emerald-600";
  if (status === "failed" || status === "needs_review") return "text-rose-600";
  if (status === "running") return "text-blue-600";
  return "text-muted-foreground";
}

export function statusBg(status: string | null | undefined): string {
  if (!status) return "bg-muted text-muted-foreground";
  if (status === "succeeded") return "bg-emerald-100 text-emerald-800";
  if (status === "failed" || status === "needs_review") return "bg-rose-100 text-rose-800";
  if (status === "running") return "bg-blue-100 text-blue-800";
  return "bg-muted text-muted-foreground";
}
