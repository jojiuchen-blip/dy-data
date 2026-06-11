import type { ReactNode } from "react";

interface FilterFieldProps {
  label: string;
  children: ReactNode;
}

export function FilterField({ label, children }: FilterFieldProps) {
  return (
    <label className="filter-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

interface FilterBarProps {
  children: ReactNode;
}

export function FilterBar({ children }: FilterBarProps) {
  return <div className="filter-bar">{children}</div>;
}
