import type { ButtonHTMLAttributes, ReactNode } from "react";
import { SolarIcon, type SolarIconName } from "./SolarIcon";

type ButtonVariant = "primary" | "secondary" | "soft" | "danger" | "text";
type ButtonSize = "sm" | "md" | "touch";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: SolarIconName;
  iconPosition?: "start" | "end";
  loading?: boolean;
  size?: ButtonSize;
  variant?: ButtonVariant;
}

interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  icon: SolarIconName;
  label: string;
  size?: ButtonSize;
  variant?: Exclude<ButtonVariant, "text">;
}

const legacyClassByVariant: Record<ButtonVariant, string> = {
  danger: "ui-button--danger",
  primary: "primary-button",
  secondary: "ghost-button",
  soft: "ui-button--soft",
  text: "link-button",
};

function buttonClassName(
  variant: ButtonVariant,
  size: ButtonSize,
  extraClassName?: string,
): string {
  return [
    "ui-button",
    `ui-button--${variant}`,
    `ui-button--${size}`,
    legacyClassByVariant[variant],
    extraClassName,
  ]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  children,
  className,
  disabled,
  icon,
  iconPosition = "start",
  loading = false,
  size = "md",
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  const iconNode = icon ? <SolarIcon name={icon} size={16} /> : null;
  const content: ReactNode[] = [];

  if (loading) {
    content.push(<span aria-hidden="true" className="ui-button__spinner" key="loading" />);
  } else if (iconNode && iconPosition === "start") {
    content.push(<span className="ui-button__icon" key="icon-start">{iconNode}</span>);
  }

  content.push(<span className="ui-button__label" key="label">{children}</span>);

  if (!loading && iconNode && iconPosition === "end") {
    content.push(<span className="ui-button__icon" key="icon-end">{iconNode}</span>);
  }

  return (
    <button
      className={buttonClassName(variant, size, className)}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {content}
    </button>
  );
}

export function IconButton({
  className,
  disabled,
  icon,
  label,
  size = "md",
  type = "button",
  variant = "secondary",
  ...props
}: IconButtonProps) {
  return (
    <button
      aria-label={label}
      className={[
        "ui-icon-button",
        `ui-icon-button--${variant}`,
        `ui-icon-button--${size}`,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      disabled={disabled}
      type={type}
      {...props}
    >
      <SolarIcon name={icon} size={size === "sm" ? 16 : 18} />
    </button>
  );
}
