import type { Workspace } from "./types";

interface Props {
  workspaces: Workspace[];
  selected: string | null;
  onChange: (id: string | null) => void;
}

export function WorkspaceFilter({ workspaces, selected, onChange }: Props) {
  return (
    <select
      className="filter-select"
      value={selected ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">All workspaces</option>
      {workspaces.map((w) => (
        <option key={w.id} value={w.id}>
          {w.name}
        </option>
      ))}
    </select>
  );
}
