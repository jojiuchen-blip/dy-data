import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import "./GuidedTour.css";

export interface GuidedTourStep {
  id: string;
  title: string;
  description: string;
  target: string | null;
}

export interface GuidedTourProps {
  step: GuidedTourStep;
  index: number;
  total: number;
  pending?: boolean;
  notice?: string;
  nextLabel?: string;
  onNext: () => void;
  onPrevious?: () => void;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}

interface ViewportRect {
  bottom: number;
  height: number;
  left: number;
  right: number;
  top: number;
  width: number;
}

interface ScrollSnapshot {
  element: HTMLElement | null;
  isWindow: boolean;
  left: number;
  top: number;
}

interface PopoverPosition {
  left: number;
  top: number;
}

function viewportSize() {
  return {
    height: window.innerHeight || document.documentElement.clientHeight || 1,
    width: window.innerWidth || document.documentElement.clientWidth || 1,
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}

function sameRect(previous: ViewportRect | null, next: ViewportRect | null): boolean {
  if (!previous || !next) return previous === next;
  return (
    previous.bottom === next.bottom &&
    previous.height === next.height &&
    previous.left === next.left &&
    previous.right === next.right &&
    previous.top === next.top &&
    previous.width === next.width
  );
}

function isVisibleElement(element: HTMLElement): boolean {
  if (!element.isConnected) return false;

  const style = window.getComputedStyle(element);
  if (
    style.display === "none" ||
    style.visibility === "hidden" ||
    style.visibility === "collapse" ||
    style.opacity === "0"
  ) {
    return false;
  }

  const rect = element.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) return true;
  return Array.from(element.getClientRects()).some(
    (clientRect) => clientRect.width > 0 && clientRect.height > 0,
  );
}

function findTarget(selector: string | null): HTMLElement | null {
  if (!selector) return null;

  try {
    return (
      Array.from(document.querySelectorAll<HTMLElement>(selector)).find(isVisibleElement) ??
      null
    );
  } catch {
    return null;
  }
}

function clipsOverflow(value: string): boolean {
  return value === "auto" || value === "clip" || value === "hidden" || value === "scroll";
}

function clippedTargetRect(target: HTMLElement): ViewportRect | null {
  const viewport = viewportSize();
  const targetRect = target.getBoundingClientRect();
  let left = Math.max(0, targetRect.left);
  let top = Math.max(0, targetRect.top);
  let right = Math.min(viewport.width, targetRect.right);
  let bottom = Math.min(viewport.height, targetRect.bottom);

  let ancestor = target.parentElement;
  while (ancestor) {
    const style = window.getComputedStyle(ancestor);
    if (clipsOverflow(style.overflowX) || clipsOverflow(style.overflowY)) {
      const ancestorRect = ancestor.getBoundingClientRect();
      left = Math.max(left, ancestorRect.left);
      top = Math.max(top, ancestorRect.top);
      right = Math.min(right, ancestorRect.right);
      bottom = Math.min(bottom, ancestorRect.bottom);
    }
    ancestor = ancestor.parentElement;
  }

  if (right <= left || bottom <= top) return null;
  return {
    bottom,
    height: bottom - top,
    left,
    right,
    top,
    width: right - left,
  };
}

function scrollableAncestors(element: HTMLElement): HTMLElement[] {
  const ancestors: HTMLElement[] = [];
  let ancestor = element.parentElement;
  while (ancestor) {
    const style = window.getComputedStyle(ancestor);
    const scrollableX = clipsOverflow(style.overflowX) && ancestor.scrollWidth > ancestor.clientWidth;
    const scrollableY = clipsOverflow(style.overflowY) && ancestor.scrollHeight > ancestor.clientHeight;
    if (scrollableX || scrollableY) ancestors.push(ancestor);
    ancestor = ancestor.parentElement;
  }
  return ancestors;
}

function scrollTargetToEdge(element: HTMLElement, block: "end" | "start"): boolean {
  const viewport = viewportSize();
  let changed = false;
  const ancestors = scrollableAncestors(element);

  for (const ancestor of ancestors) {
    const targetRect = element.getBoundingClientRect();
    const ancestorRect = ancestor.getBoundingClientRect();
    const edge = block === "start"
      ? Math.max(12, ancestorRect.top + 12)
      : Math.min(viewport.height - 12, ancestorRect.bottom - 12);
    const delta = block === "start" ? targetRect.top - edge : targetRect.bottom - edge;
    if (Math.abs(delta) <= 1) continue;

    const maximum = Math.max(0, ancestor.scrollHeight - ancestor.clientHeight);
    const nextScrollTop = clamp(ancestor.scrollTop + delta, 0, maximum);
    if (Math.abs(nextScrollTop - ancestor.scrollTop) <= 1) continue;
    ancestor.scrollTo({ top: nextScrollTop, left: ancestor.scrollLeft, behavior: "instant" });
    changed = true;
  }

  if (ancestors.length === 0) {
    const targetRect = element.getBoundingClientRect();
    const edge = block === "start" ? 12 : viewport.height - 12;
    const delta = block === "start" ? targetRect.top - edge : targetRect.bottom - edge;
    if (Math.abs(delta) > 1) {
      const nextScrollTop = Math.max(0, window.scrollY + delta);
      if (Math.abs(nextScrollTop - window.scrollY) > 1) {
        try {
          window.scrollTo({ left: window.scrollX, top: nextScrollTop, behavior: "auto" });
        } catch {
          window.scrollTo(window.scrollX, nextScrollTop);
        }
        changed = true;
      }
    }
  }

  return changed;
}

function intersects(first: ViewportRect, second: ViewportRect): boolean {
  return !(
    first.right <= second.left ||
    first.left >= second.right ||
    first.bottom <= second.top ||
    first.top >= second.bottom
  );
}

function insideViewport(
  position: PopoverPosition,
  width: number,
  height: number,
  viewport: { height: number; width: number },
): boolean {
  return (
    position.left >= 12 &&
    position.top >= 12 &&
    position.left + width <= viewport.width - 12 &&
    position.top + height <= viewport.height - 12
  );
}

function choosePopoverPosition(
  targetRect: ViewportRect,
  panelWidth: number,
  panelHeight: number,
): PopoverPosition | null {
  const viewport = viewportSize();
  const gap = 14;
  const centeredLeft = clamp(
    targetRect.left + (targetRect.width - panelWidth) / 2,
    12,
    viewport.width - panelWidth - 12,
  );
  const alignedTop = clamp(targetRect.top, 12, viewport.height - panelHeight - 12);
  const candidates: PopoverPosition[] = [
    {
      left: centeredLeft,
      top: targetRect.bottom + gap,
    },
    {
      left: centeredLeft,
      top: targetRect.top - panelHeight - gap,
    },
    {
      left: targetRect.right + gap,
      top: alignedTop,
    },
    {
      left: targetRect.left - panelWidth - gap,
      top: alignedTop,
    },
  ];

  const available = candidates.find((candidate) => {
    const box = {
      bottom: candidate.top + panelHeight,
      height: panelHeight,
      left: candidate.left,
      right: candidate.left + panelWidth,
      top: candidate.top,
      width: panelWidth,
    };
    return insideViewport(candidate, panelWidth, panelHeight, viewport) && !intersects(box, targetRect);
  });
  if (available) return available;
  return null;
}

function samePanelStyle(
  previous: CSSProperties | undefined,
  next: CSSProperties | undefined,
): boolean {
  if (!previous || !next) return previous === next;
  return (
    previous.left === next.left &&
    previous.top === next.top &&
    previous.width === next.width &&
    previous.maxWidth === next.maxWidth &&
    previous.transform === next.transform &&
    previous.position === next.position
  );
}

export function GuidedTour({
  index,
  nextLabel = "下一步",
  notice,
  onClose,
  onNext,
  onPrevious,
  pending = false,
  returnFocusRef,
  step,
  total,
}: GuidedTourProps) {
  const targetRef = useRef<HTMLElement | null>(null);
  const scrollSnapshotsRef = useRef<ScrollSnapshot[]>([]);
  const waitTimerRef = useRef<number | null>(null);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [targetRect, setTargetRect] = useState<ViewportRect | null>(null);
  const [panelStyle, setPanelStyle] = useState<CSSProperties | undefined>(undefined);
  const [waitingExpired, setWaitingExpired] = useState(false);
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [placementUnavailable, setPlacementUnavailable] = useState(false);
  const restoreScrollPositionsRef = useRef<() => void>(() => undefined);
  const panelSizeRef = useRef<{ height: number; width: number } | null>(null);
  const viewportSizeRef = useRef<{ height: number; width: number } | null>(null);
  const placementRetryRef = useRef<string | null>(null);
  const placementRetryTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => restoreScrollPositionsRef.current();
  }, []);

  useEffect(() => {
    targetRef.current = null;
    setTarget(null);
    setTargetRect(null);
    setPanelStyle(undefined);
    setPlacementUnavailable(false);
    placementRetryRef.current = null;
    if (placementRetryTimerRef.current !== null) {
      window.clearTimeout(placementRetryTimerRef.current);
      placementRetryTimerRef.current = null;
    }

    let disposed = false;
    let frame: number | null = null;
    let frameUsesAnimationFrame = false;
    let observedTarget: HTMLElement | null = null;
    let observedPanel: HTMLElement | null = null;
    let shouldScroll = true;

    const rememberScrollPositions = (element: HTMLElement) => {
      if (!scrollSnapshotsRef.current.some((snapshot) => snapshot.isWindow)) {
        scrollSnapshotsRef.current.push({
          element: null,
          isWindow: true,
          left: window.scrollX,
          top: window.scrollY,
        });
      }

      for (const ancestor of scrollableAncestors(element)) {
        if (scrollSnapshotsRef.current.some((snapshot) => snapshot.element === ancestor)) continue;
        scrollSnapshotsRef.current.push({
          element: ancestor,
          isWindow: false,
          left: ancestor.scrollLeft,
          top: ancestor.scrollTop,
        });
      }
    };

    const restoreScrollPositions = () => {
      for (const snapshot of scrollSnapshotsRef.current) {
        if (snapshot.isWindow) {
          if (window.scrollX !== snapshot.left || window.scrollY !== snapshot.top) {
            try {
              window.scrollTo({ left: snapshot.left, top: snapshot.top, behavior: "auto" });
            } catch {
              window.scrollTo(snapshot.left, snapshot.top);
            }
          }
        } else if (snapshot.element) {
          if (
            snapshot.element.scrollLeft !== snapshot.left ||
            snapshot.element.scrollTop !== snapshot.top
          ) {
            snapshot.element.scrollLeft = snapshot.left;
            snapshot.element.scrollTop = snapshot.top;
          }
        }
      }
    };
    restoreScrollPositionsRef.current = restoreScrollPositions;

    const cancelFrame = () => {
      if (frame === null) return;
      if (frameUsesAnimationFrame) {
        window.cancelAnimationFrame(frame);
      } else {
        window.clearTimeout(frame);
      }
      frame = null;
    };

    let resizeObserver: ResizeObserver | null = null;

    const update = () => {
      frame = null;
      if (disposed) return;

      const resolvedTarget = findTarget(step.target);
      if (resolvedTarget !== targetRef.current) {
        targetRef.current = resolvedTarget;
        shouldScroll = Boolean(resolvedTarget);
        setTarget((previous) => (previous === resolvedTarget ? previous : resolvedTarget));
      }

      const panel = document.querySelector<HTMLElement>(".guided-tour");
      if (panel !== observedPanel) {
        if (observedPanel) resizeObserver?.unobserve(observedPanel);
        observedPanel = panel;
        if (panel) resizeObserver?.observe(panel);
      }
      if (resolvedTarget !== observedTarget) {
        if (observedTarget) resizeObserver?.unobserve(observedTarget);
        observedTarget = resolvedTarget;
        if (resolvedTarget) resizeObserver?.observe(resolvedTarget);
      }

      if (resolvedTarget && shouldScroll) {
        rememberScrollPositions(resolvedTarget);
        if (typeof resolvedTarget.scrollIntoView === "function") {
          try {
            resolvedTarget.scrollIntoView({
              // Measure the settled target in the same frame; a pending smooth
              // scroll could overwrite the edge alignment used by narrow screens.
              behavior: "instant",
              block: "center",
              inline: "nearest",
            });
          } catch {
            resolvedTarget.scrollIntoView();
          }
        }
        shouldScroll = false;
      }

      const nextRect = resolvedTarget ? clippedTargetRect(resolvedTarget) : null;
      setTargetRect((previous) => (sameRect(previous, nextRect) ? previous : nextRect));
    };

    const schedule = () => {
      if (disposed || frame !== null) return;
      if (typeof window.requestAnimationFrame === "function") {
        frameUsesAnimationFrame = true;
        frame = window.requestAnimationFrame(update);
      } else {
        frameUsesAnimationFrame = false;
        frame = window.setTimeout(update, 0);
      }
    };

    const notifyLayoutChange = () => {
      if (disposed) return;
      const panel = document.querySelector<HTMLElement>(".guided-tour");
      const panelRect = panel?.getBoundingClientRect();
      if (
        panelRect &&
        (!panelSizeRef.current ||
          panelSizeRef.current.width !== panelRect.width ||
          panelSizeRef.current.height !== panelRect.height)
      ) {
        panelSizeRef.current = {
          height: panelRect.height,
          width: panelRect.width,
        };
        setLayoutRevision((revision) => revision + 1);
      }
      schedule();
    };

    resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(notifyLayoutChange)
      : null;
    const mutationObserver = typeof MutationObserver !== "undefined"
      ? new MutationObserver((mutations) => {
          const relevant = mutations.some((mutation) => {
            const mutationTarget = mutation.target;
            return !(mutationTarget instanceof Element && mutationTarget.closest(".guided-tour"));
          });
          if (relevant) schedule();
        })
      : null;

    const handleResize = () => {
      const nextViewport = viewportSize();
      const previousViewport = viewportSizeRef.current;
      if (
        !previousViewport ||
        previousViewport.width !== nextViewport.width ||
        previousViewport.height !== nextViewport.height
      ) {
        viewportSizeRef.current = nextViewport;
        placementRetryRef.current = null;
        setPlacementUnavailable(false);
        setLayoutRevision((revision) => revision + 1);
      }
      schedule();
    };

    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", schedule, true);
    mutationObserver?.observe(document.body, {
      attributes: true,
      childList: true,
      subtree: true,
    });
    schedule();

    return () => {
      disposed = true;
      cancelFrame();
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", schedule, true);
      if (placementRetryTimerRef.current !== null) {
        window.clearTimeout(placementRetryTimerRef.current);
        placementRetryTimerRef.current = null;
      }
    };
  }, [step.id, step.target]);

  const targetReady = Boolean(target && targetRect && !placementUnavailable);

  useEffect(() => {
    setWaitingExpired(false);
    if (waitTimerRef.current !== null) {
      window.clearTimeout(waitTimerRef.current);
      waitTimerRef.current = null;
    }

    const needsWait = pending || (Boolean(step.target) && !targetReady);
    if (!needsWait) return undefined;

    waitTimerRef.current = window.setTimeout(() => {
      waitTimerRef.current = null;
      setWaitingExpired(true);
    }, 8000);

    return () => {
      if (waitTimerRef.current !== null) {
        window.clearTimeout(waitTimerRef.current);
        waitTimerRef.current = null;
      }
    };
  }, [pending, step.id, step.target, targetReady]);

  useLayoutEffect(() => {
    if (!targetRect || placementUnavailable) {
      setPanelStyle((previous) => (previous === undefined ? previous : undefined));
      return;
    }

    const panel = document.querySelector<HTMLElement>(".guided-tour");
    if (!panel) return;

    const viewport = viewportSize();
    const panelWidth = Math.min(360, Math.max(0, viewport.width - 24));
    const measuredHeight = panel.getBoundingClientRect().height;
    const panelHeight = Math.min(
      Math.max(measuredHeight || 260, 160),
      Math.max(0, viewport.height - 24),
    );
    const position = choosePopoverPosition(targetRect, panelWidth, panelHeight);
    if (!position) {
      const startRetryKey = `${step.id}:start`;
      const endRetryKey = `${step.id}:end`;
      const nextBlock =
        placementRetryRef.current === startRetryKey
          ? "end"
          : placementRetryRef.current === endRetryKey
            ? null
            : "start";
      if (nextBlock) {
        placementRetryRef.current = `${step.id}:${nextBlock}`;
        if (placementRetryTimerRef.current !== null) {
          window.clearTimeout(placementRetryTimerRef.current);
        }
        const changedScroll = target ? scrollTargetToEdge(target, nextBlock) : false;
        if (!changedScroll && target && typeof target.scrollIntoView === "function") {
          try {
            target.scrollIntoView({
              behavior: "instant",
              block: nextBlock,
              inline: "nearest",
            });
          } catch {
            target.scrollIntoView();
          }
        }
        // Do not retry with the pre-scroll rectangle. React and the scroll
        // observer may otherwise exhaust both edges before the next frame.
        const movedRect = target ? clippedTargetRect(target) : null;
        setTargetRect((previous) => sameRect(previous, movedRect) ? previous : movedRect);
        placementRetryTimerRef.current = window.setTimeout(() => {
          placementRetryTimerRef.current = null;
          setLayoutRevision((revision) => revision + 1);
        }, 50);
        return;
      }

      setPlacementUnavailable(true);
      setPanelStyle(undefined);
      return;
    }
    placementRetryRef.current = null;
    if (placementRetryTimerRef.current !== null) {
      window.clearTimeout(placementRetryTimerRef.current);
      placementRetryTimerRef.current = null;
    }
    const nextStyle: CSSProperties = {
      left: Math.round(position.left),
      maxWidth: "calc(100vw - 24px)",
      position: "fixed",
      top: Math.round(position.top),
      transform: "none",
      width: panelWidth,
    };

    setPanelStyle((previous) => (samePanelStyle(previous, nextStyle) ? previous : nextStyle));
  }, [
    layoutRevision,
    notice,
    pending,
    placementUnavailable,
    step.id,
    target,
    targetRect,
    waitingExpired,
  ]);

  const isMissingTarget = Boolean(step.target) && !targetReady;
  const showEndAction = waitingExpired || placementUnavailable;
  const nextDisabled = pending && !showEndAction;
  const spotlightStyle: CSSProperties | undefined = targetRect && !placementUnavailable
    ? {
        height: Math.min(
          viewportSize().height - Math.max(0, targetRect.top - 4),
          targetRect.height + 8,
        ),
        left: Math.max(0, targetRect.left - 4),
        top: Math.max(0, targetRect.top - 4),
        width: Math.min(
          viewportSize().width - Math.max(0, targetRect.left - 4),
          targetRect.width + 8,
        ),
      }
    : { display: "none" };

  const backdropClassName = [
    "guided-tour-backdrop",
    targetRect && !placementUnavailable ? "" : "guided-tour-backdrop--no-target",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Dialog
      actions={
        <div className="guided-tour__actions">
          <Button
            className="guided-tour__skip"
            onClick={onClose}
            size="touch"
            variant="text"
          >
            跳过引导
          </Button>
          <div className="guided-tour__navigation">
            {onPrevious ? (
              <Button onClick={onPrevious} size="touch" variant="secondary">
                上一步
              </Button>
            ) : null}
            <Button
              disabled={nextDisabled}
              onClick={showEndAction ? onClose : onNext}
              size="touch"
              variant="primary"
            >
              {showEndAction ? "结束引导" : nextLabel}
            </Button>
          </div>
        </div>
      }
      backdropClassName={backdropClassName}
      backdropContent={
        step.target ? (
          <div
            aria-hidden="true"
            className="guided-tour__spotlight"
            data-tour-target={step.target}
            style={spotlightStyle}
          />
        ) : null
      }
      closeLabel="退出新手引导"
      description={step.description}
      layer={20}
      onClose={onClose}
      open
      panelClassName="guided-tour"
      panelStyle={panelStyle}
      returnFocusRef={returnFocusRef}
      title={step.title}
    >
      <div className="guided-tour__content" data-clue-tour-step={step.id}>
        <p aria-atomic="true" aria-live="polite" className="guided-tour__progress">
          第 {index + 1} / {total} 步
          <span className="visually-hidden">：{step.title}</span>
        </p>
        {notice ? (
          <p aria-live="polite" className="guided-tour__notice" role="status">
            {notice}
          </p>
        ) : null}
        {placementUnavailable ? (
          <p aria-live="polite" className="guided-tour__notice" role="status">
            当前区域无法在视口内同时展示说明和高亮，你可以结束引导后继续操作。
          </p>
        ) : null}
        {isMissingTarget && !placementUnavailable ? (
          <p aria-live="polite" className="guided-tour__notice" role="status">
            正在查找当前页面的操作区域，请稍候；如果持续找不到，可结束引导。
          </p>
        ) : null}
        {waitingExpired ? (
          <p aria-live="assertive" className="guided-tour__notice" role="alert">
            暂时找不到对应区域，已停止等待。你可以结束引导，稍后从入口重新开始。
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
