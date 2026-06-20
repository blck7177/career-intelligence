import { cn } from "@/lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "outline" | "destructive";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        variant === "default" && "bg-zinc-900 text-zinc-50",
        variant === "secondary" && "bg-zinc-100 text-zinc-700",
        variant === "outline" && "border border-zinc-200 text-zinc-700",
        variant === "destructive" && "bg-rose-100 text-rose-700",
        className,
      )}
      {...props}
    />
  );
}
