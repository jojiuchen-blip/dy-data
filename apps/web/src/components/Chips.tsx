import type { ButtonHTMLAttributes, ReactNode } from "react";
import { SolarIcon } from "./SolarIcon";

export type ChipTone =
  | "neutral"
  | "brand"
  | "success"
  | "info"
  | "warning"
  | "danger";

interface BaseChipProps {
  children: ReactNode;
  className?: string;
  tone?: ChipTone;
}

interface FilterChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
}

function chipClass(kind: string, tone: ChipTone, className?: string): string {
  return ["ui-chip", kind, `ui-chip--${tone}`, className]
    .filter(Boolean)
    .join(" ");
}

export function StatusChip({
  children,
  className,
  tone = "neutral",
}: BaseChipProps) {
  return <span className={chipClass("ui-status-chip", tone, className)}>{children}</span>;
}

export function CountPill({
  children,
  className,
  tone = "neutral",
}: BaseChipProps) {
  return <span className={chipClass("ui-count-pill", tone, className)}>{children}</span>;
}

export function RoleBadge({
  children,
  className,
  tone = "neutral",
}: BaseChipProps) {
  return <span className={chipClass("ui-role-badge", tone, className)}>{children}</span>;
}

export function FilterChip({
  children,
  className,
  type = "button",
  ...props
}: FilterChipProps) {
  return (
    <button
      className={chipClass("ui-filter-chip", "neutral", className)}
      type={type}
      {...props}
    >
      <span>{children}</span>
      <SolarIcon name="close" size={14} />
    </button>
  );
}
