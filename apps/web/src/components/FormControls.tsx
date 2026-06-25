import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { SolarIcon } from "./SolarIcon";

export interface SelectFieldOption {
  disabled?: boolean;
  label: string;
  meta?: ReactNode;
  value: string;
}

interface FieldShellProps {
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  error?: string;
  helperText?: ReactNode;
  id?: string;
  label: string;
  meta?: ReactNode;
}

interface SelectFieldProps extends Omit<FieldShellProps, "children"> {
  emptyLabel?: string;
  onChange: (value: string) => void;
  options: SelectFieldOption[];
  placeholder?: string;
  readOnly?: boolean;
  value: string;
}

interface MultiSelectFieldProps extends Omit<FieldShellProps, "children"> {
  emptyLabel?: string;
  onChange: (value: string[]) => void;
  options: SelectFieldOption[];
  readOnly?: boolean;
  value: string[];
}

function useOutsideClose<T extends HTMLElement>(
  open: boolean,
  onClose: () => void,
) {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    if (!open) return undefined;

    const handlePointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onClose();
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [onClose, open]);

  return ref;
}

function nextEnabledIndex(
  options: SelectFieldOption[],
  current: number,
  step: 1 | -1,
): number {
  if (!options.length) return 0;
  let next = current;
  for (let count = 0; count < options.length; count += 1) {
    next = Math.min(options.length - 1, Math.max(0, next + step));
    if (!options[next]?.disabled) {
      return next;
    }
    if (next === 0 || next === options.length - 1) {
      break;
    }
  }
  return current;
}

function selectedLabel(
  options: SelectFieldOption[],
  value: string,
  fallback = "请选择",
): string {
  return options.find((option) => option.value === value)?.label ?? fallback;
}

function FieldShell({
  children,
  className,
  disabled = false,
  error,
  helperText,
  id,
  label,
  meta,
}: FieldShellProps) {
  const helperId = helperText ? `${id}-helper` : undefined;
  const errorId = error ? `${id}-error` : undefined;

  return (
    <div
      className={[
        "filter-field",
        "ui-field",
        disabled ? "is-disabled" : "",
        error ? "is-error" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="ui-field__label-row">
        <label className="ui-field__label" htmlFor={id}>
          {label}
        </label>
        {meta ? <span className="ui-field__meta">{meta}</span> : null}
      </div>
      {children}
      {helperText ? (
        <p className="ui-field__helper" id={helperId}>
          {helperText}
        </p>
      ) : null}
      {error ? (
        <p className="ui-field__error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function SelectField({
  className,
  disabled = false,
  emptyLabel = "请选择",
  error,
  helperText,
  id,
  label,
  meta,
  onChange,
  options,
  placeholder,
  readOnly = false,
  value,
}: SelectFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const menuId = `${fieldId}-menu`;
  const [open, setOpen] = useState(false);
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const wrapperRef = useOutsideClose<HTMLDivElement>(open, () => setOpen(false));
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const isUnavailable = disabled || readOnly;

  useEffect(() => {
    if (open) {
      setActiveIndex(selectedIndex);
    }
  }, [open, selectedIndex]);

  const chooseOption = (option: SelectFieldOption) => {
    if (option.disabled || isUnavailable) return;
    onChange(option.value);
    setOpen(false);
    buttonRef.current?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (isUnavailable) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => nextEnabledIndex(options, current, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => nextEnabledIndex(options, current, -1));
    } else if (event.key === "Home") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex(Math.max(0, options.length - 1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open && options[activeIndex]) {
        chooseOption(options[activeIndex]);
      } else {
        setOpen(true);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  };

  const describedBy = [
    helperText ? `${fieldId}-helper` : "",
    error ? `${fieldId}-error` : "",
  ]
    .filter(Boolean)
    .join(" ") || undefined;

  return (
    <FieldShell
      className={className}
      disabled={disabled}
      error={error}
      helperText={helperText}
      id={fieldId}
      label={label}
      meta={meta}
    >
      <div className="ui-select" ref={wrapperRef}>
        <button
          aria-controls={menuId}
          aria-describedby={describedBy}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-invalid={error ? true : undefined}
          className="ui-select__trigger"
          disabled={disabled}
          id={fieldId}
          onClick={() => !readOnly && setOpen((current) => !current)}
          onKeyDown={handleKeyDown}
          ref={buttonRef}
          type="button"
        >
          <span className={value ? "" : "is-placeholder"}>
            {selectedLabel(options, value, placeholder ?? emptyLabel)}
          </span>
          <SolarIcon name="chevronDown" size={18} />
        </button>
        {open && !isUnavailable ? (
          <div className="ui-select__menu" id={menuId} role="listbox">
            {options.map((option, index) => {
              const selected = option.value === value;
              return (
                <button
                  aria-disabled={option.disabled ? true : undefined}
                  aria-selected={selected}
                  className={[
                    "ui-select__option",
                    index === activeIndex ? "is-active" : "",
                    selected ? "is-selected" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  disabled={option.disabled}
                  key={`${option.value}-${option.label}`}
                  onClick={() => chooseOption(option)}
                  onMouseEnter={() => setActiveIndex(index)}
                  role="option"
                  type="button"
                >
                  <span>{option.label}</span>
                  {option.meta ? <strong>{option.meta}</strong> : null}
                  {selected ? <SolarIcon name="check" size={16} /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </FieldShell>
  );
}

export function MultiSelectField({
  className,
  disabled = false,
  emptyLabel = "未选择",
  error,
  helperText,
  id,
  label,
  meta,
  onChange,
  options,
  readOnly = false,
  value,
}: MultiSelectFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const menuId = `${fieldId}-menu`;
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapperRef = useOutsideClose<HTMLDivElement>(open, () => setOpen(false));
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const valueSet = useMemo(() => new Set(value), [value]);
  const isUnavailable = disabled || readOnly;
  const display = value.length
    ? options
        .filter((option) => valueSet.has(option.value))
        .map((option) => option.label)
        .slice(0, 2)
        .join("、")
    : emptyLabel;
  const overflow = Math.max(0, value.length - 2);

  const toggleOption = (option: SelectFieldOption) => {
    if (option.disabled || isUnavailable) return;
    const next = valueSet.has(option.value)
      ? value.filter((item) => item !== option.value)
      : [...value, option.value];
    onChange(next);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (isUnavailable) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => nextEnabledIndex(options, current, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => nextEnabledIndex(options, current, -1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open && options[activeIndex]) {
        toggleOption(options[activeIndex]);
      } else {
        setOpen(true);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    }
  };

  return (
    <FieldShell
      className={className}
      disabled={disabled}
      error={error}
      helperText={helperText}
      id={fieldId}
      label={label}
      meta={meta}
    >
      <div className="ui-select" ref={wrapperRef}>
        <button
          aria-controls={menuId}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-invalid={error ? true : undefined}
          className="ui-select__trigger"
          disabled={disabled}
          id={fieldId}
          onClick={() => !readOnly && setOpen((current) => !current)}
          onKeyDown={handleKeyDown}
          ref={buttonRef}
          type="button"
        >
          <span className={value.length ? "" : "is-placeholder"}>
            {display}
            {overflow ? ` 等 ${value.length} 项` : ""}
          </span>
          <SolarIcon name="chevronDown" size={18} />
        </button>
        {open && !isUnavailable ? (
          <div
            aria-multiselectable="true"
            className="ui-select__menu"
            id={menuId}
            role="listbox"
          >
            {options.map((option, index) => {
              const selected = valueSet.has(option.value);
              return (
                <button
                  aria-disabled={option.disabled ? true : undefined}
                  aria-selected={selected}
                  className={[
                    "ui-select__option",
                    index === activeIndex ? "is-active" : "",
                    selected ? "is-selected" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  disabled={option.disabled}
                  key={option.value}
                  onClick={() => toggleOption(option)}
                  onMouseEnter={() => setActiveIndex(index)}
                  role="option"
                  type="button"
                >
                  <span>{option.label}</span>
                  {option.meta ? <strong>{option.meta}</strong> : null}
                  {selected ? <SolarIcon name="check" size={16} /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </FieldShell>
  );
}
