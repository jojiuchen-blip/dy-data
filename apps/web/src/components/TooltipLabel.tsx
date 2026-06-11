import type { ReactNode } from "react";

interface TooltipLabelProps {
  label: ReactNode;
  description?: string;
}

export function TooltipLabel({ label, description }: TooltipLabelProps) {
  return (
    <span className="tooltip-label">
      <span>{label}</span>
      {description ? (
        <span
          aria-label={description}
          className="tooltip-trigger"
          data-tooltip={description}
          tabIndex={0}
        >
          ?
        </span>
      ) : null}
    </span>
  );
}
