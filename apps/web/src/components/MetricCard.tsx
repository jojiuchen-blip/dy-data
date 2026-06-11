import type { ReactNode } from "react";
import { TooltipLabel } from "./TooltipLabel";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  description?: string;
  meta?: ReactNode;
  href?: string;
  tone?: "green" | "blue" | "amber";
}

export function MetricCard({
  label,
  value,
  description,
  meta,
  href,
  tone = "green",
}: MetricCardProps) {
  const content = (
    <>
      <div className="metric-card__label">
        <TooltipLabel label={label} description={description} />
      </div>
      <div className="metric-card__value">{value}</div>
      {meta ? <div className="metric-card__meta">{meta}</div> : null}
    </>
  );

  if (href) {
    return (
      <a className={`metric-card metric-card--${tone}`} href={href}>
        {content}
      </a>
    );
  }

  return <div className={`metric-card metric-card--${tone}`}>{content}</div>;
}
