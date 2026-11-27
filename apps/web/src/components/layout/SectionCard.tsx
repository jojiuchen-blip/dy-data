import type { ReactNode } from "react";

export type SectionCardTone = "default" | "recessed";

export interface SectionCardProps {
  actions?: ReactNode;
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
  description?: ReactNode;
  eyebrow?: ReactNode;
  id?: string;
  title?: ReactNode;
  tone?: SectionCardTone;
  workspace?: boolean;
}

export function SectionCard({
  actions,
  ariaLabel,
  children,
  className,
  description,
  eyebrow,
  id,
  title,
  tone = "default",
  workspace = false,
}: SectionCardProps) {
  return (
    <section
      aria-label={ariaLabel}
      className={[
        "ui-section-card",
        tone === "recessed" ? "ui-section-card--recessed" : "",
        workspace ? "ui-section-card--workspace content-section--data-workspace" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      id={id}
    >
      {title || description || eyebrow || actions ? (
        <div className="ui-section-card__header">
          <div className="ui-section-card__titles">
            {eyebrow ? <p className="ui-section-card__eyebrow">{eyebrow}</p> : null}
            {title ? <h2 className="ui-section-card__title">{title}</h2> : null}
            {description ? (
              <p className="ui-section-card__description">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="ui-section-card__actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
