import { useId, useState, type ChangeEvent, type DragEvent } from "react";
import { SolarIcon } from "../SolarIcon";

export interface FileDropzoneProps {
  accept?: string;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
  fileName?: string | null;
  hint?: string;
  id?: string;
  inputKey?: string | number;
  label: string;
  onFileChange: (file: File | null) => void;
  placeholder?: string;
  triggerLabel?: string;
}

export function FileDropzone({
  accept,
  ariaLabel,
  className,
  disabled = false,
  fileName,
  hint = "支持点击选择或拖拽上传",
  id,
  inputKey,
  label,
  onFileChange,
  placeholder = "选择待上传文件",
  triggerLabel = "选择文件",
}: FileDropzoneProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const [dragging, setDragging] = useState(false);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onFileChange(event.target.files?.[0] ?? null);
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (disabled) return;
    event.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => {
    setDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const dropped = event.dataTransfer.files?.[0] ?? null;
    if (dropped) {
      onFileChange(dropped);
    }
  };

  return (
    <div className={["ui-file-dropzone", className].filter(Boolean).join(" ")}>
      <label className="ui-file-dropzone__label" htmlFor={fieldId}>
        {label}
      </label>
      <div
        className={[
          "ui-file-dropzone__surface",
          dragging ? "is-dragging" : "",
          disabled ? "is-disabled" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <input
          accept={accept}
          aria-label={ariaLabel ?? label}
          className="ui-file-dropzone__input"
          disabled={disabled}
          id={fieldId}
          key={inputKey}
          onChange={handleChange}
          type="file"
        />
        <div className="ui-file-dropzone__info">
          <span aria-hidden="true" className="ui-file-dropzone__icon">
            <SolarIcon name="fileDownload" size={18} />
          </span>
          <div className="ui-file-dropzone__copy">
            <span className="ui-file-dropzone__primary">
              {fileName || placeholder}
            </span>
            <span className="ui-file-dropzone__hint">{hint}</span>
          </div>
        </div>
        <span aria-hidden="true" className="ui-file-dropzone__trigger">
          {fileName ? "更换文件" : triggerLabel}
        </span>
      </div>
    </div>
  );
}
