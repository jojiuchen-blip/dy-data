import type { ReactNode } from "react";
import { SolarIcon, type SolarIconName } from "../SolarIcon";

export type CalloutTone =
  | "neutral"
  | "info"
  | "warm"
  | "warning"
  | "success"
  | "danger"
  | "brand";

export interface CalloutBannerProps {
  actions?: ReactNode;
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
  icon?: SolarIconName;
  role?: "status" | "alert" | "region";
  title?: ReactNode;
  tone?: CalloutTone;
}

const DEFAULT_ICONS: Record<CalloutTone, SolarIconName> = {
  neutral: "question",
  info: "question",
  warm: "details",
  warning: "question",
  success: "check",
  danger: "close",
  brand: "details",
};

export function CalloutBanner({
  actions,
  ariaLabel,
  children,
  className,
  icon,
  role,
  title,
  tone = "neutral",
}: CalloutBannerProps) {
  const iconName = icon ?? DEFAULT_ICONS[tone];
  return (
    <section
      aria-label={ariaLabel}
      className={[
        "ui-callout",
        tone !== "neutral" ? `ui-callout--${tone}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      role={role}
    >
      <SolarIcon className="ui-callout__icon" name={iconName} size={18} />
      <div className="ui-callout__body">
        {title ? <strong className="ui-callout__title">{title}</strong> : null}
        <div>{children}</div>
      </div>
      {actions ? <div className="ui-callout__actions">{actions}</div> : null}
    </section>
  );
}
