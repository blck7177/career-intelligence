"use client";

/**
 * The gate in front of the only control in either ritual that writes a
 * permanent suppression.
 *
 * Dropping a to-do is `op: "dismiss"`, which `_suppressed()` reads as a
 * lifetime veto for that (application, type) — the rule will not raise it
 * again, ever. The single-row version of this says so out loud
 * ("dismissed — the suppression set remembers it"); the batch versions in the
 * two wizards said nothing at all, and could write N of them from one click in
 * a flow the user is moving through quickly. The morning ritual is the sharper
 * case: the approved design has no drop option there at all, only "move to
 * tomorrow".
 *
 * So the consequence is stated where the decision is finalised, and the commit
 * button does not arm until it has been read. It appears only when something is
 * actually being dropped — a confirmation that shows up every time is one you
 * learn to click past without reading, which is the failure mode the research
 * warns about for exactly this control.
 *
 * Shared by both wizards on purpose: two copies of a safety gate is two gates
 * free to drift, and this codebase has fixed that class of bug four times.
 */
export function DropAcknowledgement({
  count,
  checked,
  onChange,
  label,
}: {
  count: number;
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  if (count === 0) return null;
  return (
    <label
      className="mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs cursor-pointer"
      style={{
        borderColor: "var(--warn-fg)",
        background: "var(--warn-bg)",
        color: "var(--warn-fg)",
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 shrink-0"
      />
      <span>{label}</span>
    </label>
  );
}

/** Whether the commit button stays disabled. One definition, two wizards: the
 *  rule for when a permanent bulk suppression may proceed should not be
 *  something each flow re-decides. */
export function dropGateBlocks(count: number, acknowledged: boolean): boolean {
  return count > 0 && !acknowledged;
}
