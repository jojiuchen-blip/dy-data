import {
  useEffect,
  useId,
  useRef,
  type MouseEvent,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Button, IconButton } from "./Button";

interface DialogProps {
  actions?: ReactNode;
  backdropClassName?: string;
  bodyClassName?: string;
  backdropContent?: ReactNode;
  children: ReactNode;
  closeDisabled?: boolean;
  closeOnBackdrop?: boolean;
  closeLabel?: string;
  description?: ReactNode;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  layer?: number;
  onClose: () => void;
  open: boolean;
  panelClassName?: string;
  panelStyle?: CSSProperties;
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

interface DialogStackEntry {
  backdropRef: React.RefObject<HTMLDivElement | null>;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  layerRef: React.RefObject<number>;
  order: number;
  panelRef: React.RefObject<HTMLElement | null>;
  previousFocus: HTMLElement | null;
  registered: boolean;
  returnFocusRef?: React.RefObject<HTMLElement | null>;
}

const dialogStack: DialogStackEntry[] = [];
let dialogOrder = 0;
let inertRoot: HTMLElement | null = null;
let previousInertState: { present: boolean; value: string | null } | null = null;

function topDialog(): DialogStackEntry | null {
  return dialogStack.reduce<DialogStackEntry | null>((top, candidate) => {
    if (!top) return candidate;
    if (candidate.layerRef.current > top.layerRef.current) return candidate;
    if (
      candidate.layerRef.current === top.layerRef.current &&
      candidate.order > top.order
    ) {
      return candidate;
    }
    return top;
  }, null);
}

function isTopDialog(entry: DialogStackEntry): boolean {
  return topDialog() === entry;
}

function updateStackPresentation() {
  const top = topDialog();
  for (const entry of dialogStack) {
    const isBehind = Boolean(top && top !== entry);
    const backdrop = entry.backdropRef.current;
    if (!backdrop) continue;
    if (isBehind) {
      backdrop.setAttribute("aria-hidden", "true");
      backdrop.setAttribute("inert", "");
    } else {
      backdrop.removeAttribute("aria-hidden");
      backdrop.removeAttribute("inert");
    }
  }
}

function registerDialog(entry: DialogStackEntry) {
  if (entry.registered) return;

  if (!dialogStack.length) {
    inertRoot = document.getElementById("root");
    previousInertState = inertRoot
      ? {
          present: inertRoot.hasAttribute("inert"),
          value: inertRoot.getAttribute("inert"),
        }
      : null;
  }

  entry.registered = true;
  entry.order = dialogOrder++;
  dialogStack.push(entry);
  inertRoot?.setAttribute("inert", "");
  updateStackPresentation();
}

function unregisterDialog(entry: DialogStackEntry) {
  const index = dialogStack.indexOf(entry);
  if (index >= 0) dialogStack.splice(index, 1);
  entry.registered = false;
  updateStackPresentation();

  if (dialogStack.length) return;

  if (inertRoot) {
    if (previousInertState?.present) {
      inertRoot.setAttribute("inert", previousInertState.value ?? "");
    } else {
      inertRoot.removeAttribute("inert");
    }
  }
  inertRoot = null;
  previousInertState = null;
}

function focusDialogEntry(entry: DialogStackEntry) {
  const panel = entry.panelRef.current;
  if (!panel) return;
  const preferred = entry.initialFocusRef?.current;
  const firstFocusable = focusableElements(panel)[0];
  (preferred ?? firstFocusable ?? panel).focus();
}

export function Dialog({
  actions,
  backdropClassName,
  bodyClassName,
  backdropContent,
  children,
  closeDisabled = false,
  closeOnBackdrop = true,
  closeLabel = "关闭弹层",
  description,
  initialFocusRef,
  layer = 0,
  onClose,
  open,
  panelClassName,
  panelStyle,
  returnFocusRef,
  title,
}: DialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const focusTimeoutRef = useRef<number | null>(null);
  const layerRef = useRef(layer);
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const stackEntryRef = useRef<DialogStackEntry | null>(null);

  layerRef.current = layer;
  if (!stackEntryRef.current) {
    stackEntryRef.current = {
      backdropRef,
      initialFocusRef,
      layerRef,
      order: 0,
      panelRef,
      previousFocus: null,
      registered: false,
      returnFocusRef,
    };
  }
  const stackEntry = stackEntryRef.current;
  stackEntry.initialFocusRef = initialFocusRef;
  stackEntry.returnFocusRef = returnFocusRef;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;

    previousFocusRef.current = document.activeElement as HTMLElement | null;
    stackEntry.previousFocus = previousFocusRef.current;
    registerDialog(stackEntry);

    focusTimeoutRef.current = window.setTimeout(() => {
      focusTimeoutRef.current = null;
      if (!stackEntry.registered || !isTopDialog(stackEntry)) return;
      const preferred = initialFocusRef?.current;
      const firstFocusable = panelRef.current ? focusableElements(panelRef.current)[0] : null;
      (preferred ?? firstFocusable ?? panelRef.current)?.focus();
    }, 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!stackEntry.registered || !isTopDialog(stackEntry)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (!closeDisabled) {
          onCloseRef.current();
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
      if (!panelRef.current.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
        return;
      }
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
      if (focusTimeoutRef.current !== null) {
        window.clearTimeout(focusTimeoutRef.current);
        focusTimeoutRef.current = null;
      }

      const wasTop = isTopDialog(stackEntry);
      unregisterDialog(stackEntry);
      const nextTop = topDialog();
      if (nextTop) {
        if (wasTop) {
          focusDialogEntry(nextTop);
        }
        return;
      }

      const returnTarget =
        returnFocusRef?.current ?? stackEntry.previousFocus ?? previousFocusRef.current;
      returnTarget?.focus?.();
    };
  }, [closeDisabled, initialFocusRef, open, returnFocusRef]);

  if (!open) {
    return null;
  }

  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (
      event.target === event.currentTarget &&
      closeOnBackdrop &&
      !closeDisabled &&
      isTopDialog(stackEntry)
    ) {
      onCloseRef.current();
    }
  };

  return createPortal(
    <div
      className={["modal-backdrop", "ui-dialog-backdrop", backdropClassName]
        .filter(Boolean)
        .join(" ")}
      ref={backdropRef}
      style={{ zIndex: `calc(var(--z-modal) + ${layer})` }}
      onMouseDown={handleBackdropMouseDown}
    >
      {backdropContent}
      <section
        aria-describedby={description ? descriptionId : undefined}
        aria-labelledby={titleId}
        aria-modal="true"
        className={["ui-dialog", panelClassName].filter(Boolean).join(" ")}
        ref={panelRef}
        style={panelStyle}
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
