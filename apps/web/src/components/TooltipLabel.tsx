import { useEffect, useId, useRef, type ReactNode } from "react";

interface TooltipLabelProps {
  label: ReactNode;
  description?: string;
  interactive?: boolean;
}

export function TooltipLabel({ label, description, interactive = false }: TooltipLabelProps) {
  const tooltipId = useId();
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(hideTimer.current), []);

  function scheduleHide(trigger?: HTMLElement) {
    if (trigger === document.activeElement) return;
    hideTimer.current = setTimeout(() => tooltipRef.current?.hidePopover(), 150);
  }

  function showTooltip(trigger: HTMLElement) {
    clearTimeout(hideTimer.current);
    const tooltip = tooltipRef.current;
    if (!tooltip) return;
    tooltip.showPopover();
    const rect = trigger.getBoundingClientRect();
    const width = tooltip.offsetWidth;
    const height = tooltip.offsetHeight;
    tooltip.style.left = `${Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - height - 8))}px`;
  }

  return (
    <span className="tooltip-label">
      <span>{label}</span>
      {description && interactive ? (
        <>
          <button
            type="button"
            aria-label={`${typeof label === "string" ? label : "指标"}口径说明`}
            aria-describedby={tooltipId}
            className="tooltip-trigger tooltip-trigger--interactive"
            onMouseEnter={(event) => showTooltip(event.currentTarget)}
            onMouseLeave={(event) => scheduleHide(event.currentTarget)}
            onFocus={(event) => showTooltip(event.currentTarget)}
            onBlur={() => tooltipRef.current?.hidePopover()}
            onClick={(event) => { event.stopPropagation(); showTooltip(event.currentTarget); }}
          >
            ?
          </button>
          <span id={tooltipId} ref={tooltipRef} role="tooltip" popover="auto" className="metric-tooltip-popover"
            onMouseEnter={() => clearTimeout(hideTimer.current)} onMouseLeave={() => scheduleHide()}>

            {description}
          </span>
        </>
      ) : description ? (
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
