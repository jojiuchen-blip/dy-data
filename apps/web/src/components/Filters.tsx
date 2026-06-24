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
  className?: string;
  id?: string;
}

export function FilterBar({ children, className, id }: FilterBarProps) {
  return (
    <div className={["filter-bar", className].filter(Boolean).join(" ")} id={id}>
      {children}
    </div>
  );
}
