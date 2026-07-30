import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type ControlSize = "sm" | "md";

interface InputVariantsOptions {
  size?: ControlSize;
  multiline?: boolean;
  className?: string;
}

/**
 * Shared skin for text controls, mirroring button-variants.ts — exported as a
 * class-name builder so a <select> or any stand-in wears the same look.
 *
 * This reconciles three flavors that had drifted apart: profile's local
 * Field/TextInput (rounded-md, px-3 py-2, ring-1/50), workspace's criteria
 * textarea (muted ground that turned white on focus, ring-2/40) and its
 * constraint inputs (rounded-md, px-2.5 py-1.5, text-xs, ring-1/50), plus
 * tracker's h-9/ring-2/20 constant. The focus ring settles on 2px @ 40%.
 *
 * `md` (40px) and `sm` (36px) deliberately mirror buttonVariants' md/sm
 * heights so a control and its adjacent button always sit level. A textarea
 * takes no height — tracker's fixed h-9 cannot apply to one, so height is
 * rows-driven.
 */
export function inputVariants({ size = "md", multiline = false, className }: InputVariantsOptions = {}) {
  return cn(
    "block w-full rounded-lg border border-[var(--border)] bg-white text-[var(--ink-primary)]",
    "placeholder:text-[var(--ink-faint)]",
    "focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/40 focus:border-[var(--primary)]",
    "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
    multiline
      ? size === "sm"
        ? "px-3 py-1.5 text-xs"
        : "px-3 py-2 text-sm"
      : size === "sm"
        ? "h-9 px-3 text-xs"
        : "h-10 px-3 text-sm",
    className,
  );
}

type InputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> & { size?: ControlSize };

export function Input({ size = "md", className, ...props }: InputProps) {
  // `size` is destructured out on purpose: it shadows the native HTML size
  // attribute, and forwarding size="sm" to the DOM would warn.
  return <input className={inputVariants({ size, className })} {...props} />;
}

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  size?: ControlSize;
  resize?: "y" | "none";
};

export function Textarea({ size = "md", resize = "y", className, ...props }: TextareaProps) {
  return (
    <textarea
      className={inputVariants({ size, multiline: true, className: cn(resize === "y" ? "resize-y" : "resize-none", className) })}
      {...props}
    />
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  /** Verbatim marker string (e.g. "required") rather than a boolean, so no copy is invented. */
  required?: string;
  /** Rendered below the control — for the one hint that sits under its input. */
  footnote?: ReactNode;
  size?: ControlSize;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}

/** label + hint wrapper, absorbed from profile's local Field/TextInput pair. */
export function Field({ label, hint, required, footnote, size = "md", htmlFor, children, className }: FieldProps) {
  return (
    <div className={className}>
      <label
        htmlFor={htmlFor}
        className={cn("block font-medium mb-1", size === "sm" ? "text-xs" : "text-sm")}
        style={{ color: size === "sm" ? "var(--ink-muted)" : "var(--ink-secondary)" }}
      >
        {label}
        {required && (
          <>
            {" "}
            <span className="font-normal" style={{ color: "var(--danger-fg)" }}>
              {required}
            </span>
          </>
        )}
      </label>
      {hint && (
        <p className={cn(size === "sm" ? "text-2xs mb-1" : "text-xs mb-1.5")} style={{ color: "var(--ink-muted)" }}>
          {hint}
        </p>
      )}
      {children}
      {footnote && (
        <p className="text-2xs mt-1" style={{ color: "var(--ink-muted)" }}>
          {footnote}
        </p>
      )}
    </div>
  );
}
