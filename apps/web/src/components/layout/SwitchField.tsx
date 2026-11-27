import { useId, type ReactNode } from "react";

export interface SwitchFieldProps {
  checked: boolean;
  className?: string;
  description?: ReactNode;
  disabled?: boolean;
  id?: string;
  label: ReactNode;
  onChange: (checked: boolean) => void;
}

export function SwitchField({
  checked,
  className,
  description,
  disabled = false,
  id,
  label,
  onChange,
}: SwitchFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const labelId = `${fieldId}-label`;
  const descriptionId = description ? `${fieldId}-desc` : undefined;

  return (
    <div className={["ui-switch-field", className].filter(Boolean).join(" ")}>
      <button
        aria-checked={checked}
        aria-describedby={descriptionId}
        aria-labelledby={labelId}
        className="ui-switch-field__control"
        disabled={disabled}
        id={fieldId}
        onClick={() => !disabled && onChange(!checked)}
        role="switch"
        type="button"
      >
        <span aria-hidden="true" className="ui-switch-field__thumb" />
      </button>
      <div className="ui-switch-field__copy">
        <span id={labelId}>{label}</span>
        {description ? (
          <span className="ui-switch-field__description" id={descriptionId}>
            {description}
          </span>
        ) : null}
      </div>
    </div>
  );
}
