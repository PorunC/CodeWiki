import type { ReactNode } from "react";

import { graphTypeLabel } from "./formatters";

export function ModeButton({
  active,
  disabled,
  icon,
  label,
  title,
  onClick
}: {
  active: boolean;
  disabled?: boolean;
  icon: ReactNode;
  label: string;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`mode-button${active ? " is-active" : ""}`}
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export function FilterGroup({
  title,
  values,
  selectedValues,
  onToggle
}: {
  title: string;
  values: string[];
  selectedValues: Set<string>;
  onToggle: (value: string) => void;
}) {
  return (
    <div className="filter-group">
      <div className="filter-title">{title}</div>
      <div className="filter-options">
        {values.length === 0 ? <span className="muted small-text">None</span> : null}
        {values.map((value) => (
          <label className="check-row" key={value}>
            <input
              type="checkbox"
              checked={selectedValues.has(value)}
              onChange={() => onToggle(value)}
            />
            <span>{graphTypeLabel(value)}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
