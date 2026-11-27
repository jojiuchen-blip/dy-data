import type { ReactNode } from "react";

export interface MetricStripProps {
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
  columns?: 3 | 4 | 5 | 6;
}

export function MetricStrip({
  ariaLabel,
  children,
  className,
  columns = 4,
}: MetricStripProps) {
  return (
    <section
      aria-label={ariaLabel}
      className={[
        "metric-grid",
        "ui-metric-strip",
        `ui-metric-strip--cols-${columns}`,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </section>
  );
}
