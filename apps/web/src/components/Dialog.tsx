import {
  useEffect,
  useId,
  useRef,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Button, IconButton } from "./Button";

interface DialogProps {
  actions?: ReactNode;
  backdropClassName?: string;
  bodyClassName?: string;
  children: ReactNode;
  closeDisabled?: boolean;
  closeLabel?: string;
  description?: ReactNode;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  open: boolean;
  panelClassName?: string;
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  title: ReactNode;
}

interface ConfirmDialogProps extends Omit<DialogProps, "children"> {
  cancelLabel?: string;
  confirmLabel?: string;
  danger?: boolean;
  message: ReactNode;
  onConfirm: () => void;
}

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(focusableSelector))
    .filter((element) => !element.hasAttribute("disabled") && !element.getAttribute("aria-hidden"));
}

export function Dialog({
  actions,
  backdropClassName,
  bodyClassName,
  children,
  closeDisabled = false,
  closeLabel = "关闭弹层",
  description,
  initialFocusRef,
  onClose,
  open,
  panelClassName,
  returnFocusRef,
  title,
}: DialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;

    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const appRoot = document.getElementById("root");
    appRoot?.setAttribute("inert", "");

    window.setTimeout(() => {
      const preferred = initialFocusRef?.current;
      const firstFocusable = panelRef.current ? focusableElements(panelRef.current)[0] : null;
      (preferred ?? firstFocusable ?? panelRef.current)?.focus();
    }, 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!closeDisabled) {
          onClose();
        }
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) {
        return;
      }

      const elements = focusableElements(panelRef.current);
      if (!elements.length) {
        event.preventDefault();
        panelRef.current.focus();
        return;
      }

      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      appRoot?.removeAttribute("inert");
      const returnTarget = returnFocusRef?.current ?? previousFocusRef.current;
      returnTarget?.focus?.();
    };
  }, [closeDisabled, initialFocusRef, onClose, open, returnFocusRef]);

  if (!open) {
    return null;
  }

  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget && !closeDisabled) {
      onClose();
    }
  };

  return createPortal(
    <div
      className={["modal-backdrop", "ui-dialog-backdrop", backdropClassName]
        .filter(Boolean)
        .join(" ")}
      onMouseDown={handleBackdropMouseDown}
    >
      <section
        aria-describedby={description ? descriptionId : undefined}
        aria-labelledby={titleId}
        aria-modal="true"
        className={["ui-dialog", panelClassName].filter(Boolean).join(" ")}
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
      >
        <header className="ui-dialog__header">
          <div>
            <h2 id={titleId}>{title}</h2>
            {description ? (
              <p className="ui-dialog__description" id={descriptionId}>
                {description}
              </p>
            ) : null}
          </div>
          <IconButton
            disabled={closeDisabled}
            icon="close"
            label={closeLabel}
            onClick={onClose}
          />
        </header>
        <div
          className={["ui-dialog__body", bodyClassName]
            .filter(Boolean)
            .join(" ")}
        >
          {children}
        </div>
        {actions ? <footer className="ui-dialog__actions">{actions}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({
  cancelLabel = "取消",
  confirmLabel = "确认",
  danger = false,
  message,
  onClose,
  onConfirm,
  ...props
}: ConfirmDialogProps) {
  return (
    <Dialog
      {...props}
      actions={
        <>
          <Button onClick={onClose} type="button" variant="secondary">
            {cancelLabel}
          </Button>
          <Button
            onClick={onConfirm}
            type="button"
            variant={danger ? "danger" : "primary"}
          >
            {confirmLabel}
          </Button>
        </>
      }
      onClose={onClose}
    >
      <p>{message}</p>
    </Dialog>
  );
}
