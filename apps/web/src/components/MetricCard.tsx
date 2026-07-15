import type { ReactNode } from "react";
import { TooltipLabel } from "./TooltipLabel";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  description?: string;
  meta?: ReactNode;
  href?: string;
  loading?: boolean;
}

export function MetricCard({
  label,
  value,
  description,
  meta,
  href,
  loading = false,
}: MetricCardProps) {
  const content = (
    <>
      <div className="metric-card__label">
        <TooltipLabel label={label} description={description} />
      </div>
      {loading ? (
        <>
          <span aria-hidden="true" className="metric-card__skeleton metric-card__skeleton--value" />
          <span aria-hidden="true" className="metric-card__skeleton metric-card__skeleton--meta" />
        </>
      ) : (
        <>
          <div className="metric-card__value">{value}</div>
          {meta ? <div className="metric-card__meta">{meta}</div> : null}
        </>
      )}
    </>
  );

  if (href) {
    return (
      <a
        aria-busy={loading || undefined}
        className="metric-card"
        href={href}
      >
        {content}
      </a>
    );
  }

  return (
    <div
      aria-busy={loading || undefined}
      className="metric-card"
    >
      {content}
    </div>
  );
}
