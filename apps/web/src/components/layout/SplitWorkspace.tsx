import type { ReactNode } from "react";

export type SplitWorkspaceRatio = "balanced" | "detail-form" | "main-aside";

export interface SplitWorkspaceProps {
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
  ratio?: SplitWorkspaceRatio;
}

export function SplitWorkspace({
  ariaLabel,
  children,
  className,
  ratio = "balanced",
}: SplitWorkspaceProps) {
  return (
    <div
      aria-label={ariaLabel}
      className={[
        "ui-split-workspace",
        ratio !== "balanced" ? `ui-split-workspace--${ratio}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </div>
  );
}
