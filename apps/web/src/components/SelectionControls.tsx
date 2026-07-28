import { useId, type KeyboardEvent, type ReactNode } from "react";

export interface SelectionOption<T extends string> {
  count?: number;
  disabled?: boolean;
  label: ReactNode;
  value: T;
}

interface TabsProps<T extends string> {
  ariaLabel: string;
  className?: string;
  itemClassName?: string;
  onChange: (value: T) => void;
  options: SelectionOption<T>[];
  value: T;
  variant?: "underline" | "segmented";
}

interface SummaryFilterProps<T extends string> {
  ariaLabel: string;
  className?: string;
  itemClassName?: string;
  onChange: (value: T) => void;
  options: SelectionOption<T>[];
  value: T;
}

function nextOptionIndex<T extends string>(
  options: SelectionOption<T>[],
  currentIndex: number,
  step: 1 | -1,
): number {
  if (!options.length) return -1;
  let nextIndex = currentIndex;
  for (let count = 0; count < options.length; count += 1) {
    nextIndex = (nextIndex + step + options.length) % options.length;
    if (!options[nextIndex]?.disabled) return nextIndex;
  }
  return currentIndex;
}

function lastEnabledIndex<T extends string>(options: SelectionOption<T>[]): number {
  for (let index = options.length - 1; index >= 0; index -= 1) {
    if (!options[index]?.disabled) return index;
  }
  return -1;
}

export function Tabs<T extends string>({
  ariaLabel,
  className,
  itemClassName,
  onChange,
  options,
  value,
  variant = "underline",
}: TabsProps<T>) {
  const generatedId = useId();
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex = index;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = nextOptionIndex(options, index, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = nextOptionIndex(options, index, -1);
    } else if (event.key === "Home") {
      nextIndex = options.findIndex((option) => !option.disabled);
    } else if (event.key === "End") {
      nextIndex = lastEnabledIndex(options);
    } else {
      return;
    }

    event.preventDefault();
    const next = options[nextIndex];
    if (!next || next.disabled) return;
    onChange(next.value);
    document.getElementById(`${generatedId}-${nextIndex}`)?.focus();
  };

  return (
    <div
      aria-label={ariaLabel}
      className={[
        "ui-tabs",
        `ui-tabs--${variant}`,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      role="tablist"
    >
      {options.map((option, index) => (
        <button
          aria-selected={value === option.value}
          className={["ui-tabs__item", itemClassName].filter(Boolean).join(" ")}
          disabled={option.disabled}
          id={`${generatedId}-${index}`}
          key={option.value}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => handleKeyDown(event, index)}
          role="tab"
          tabIndex={selectedIndex === index ? 0 : -1}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function SegmentedControl<T extends string>(props: Omit<TabsProps<T>, "variant">) {
  return <Tabs {...props} variant="segmented" />;
}

export function SummaryFilter<T extends string>({
  ariaLabel,
  className,
  itemClassName,
  onChange,
  options,
  value,
}: SummaryFilterProps<T>) {
  return (
    <div
      aria-label={ariaLabel}
      className={["ui-summary-filter", className].filter(Boolean).join(" ")}
      role="group"
    >
      {options.map((option) => (
        <button
          aria-pressed={value === option.value}
          className={["ui-summary-filter__item", itemClassName].filter(Boolean).join(" ")}
          disabled={option.disabled}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          <span>{option.label}</span>
          {typeof option.count === "number" ? <strong>{option.count}</strong> : null}
        </button>
      ))}
    </div>
  );
}
