import { badgeVariants, type BadgeVariant } from "./badge-variants";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return <span className={badgeVariants({ variant, className })} {...props} />;
}
