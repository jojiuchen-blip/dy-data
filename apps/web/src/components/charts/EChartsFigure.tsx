import {
  useEffect,
  useRef,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import {
  init,
  use,
  type EChartsCoreOption,
  type EChartsType,
} from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

use([
  AriaComponent,
  BarChart,
  GridComponent,
  LineChart,
  ScatterChart,
  SVGRenderer,
  TooltipComponent,
]);

export interface ChartPalette {
  accent: string;
  axisLine: string;
  axisText: string;
  compactBreakpoint: number;
  dataNeutralMedium: string;
  dataNeutralSoft: string;
  dataNeutralStrong: string;
  fontFamily: string;
  grid: string;
  hoverSurface: string;
  label: string;
  labelFontSize: number;
  metaFontSize: number;
  neutral: string;
  neutralFaint: string;
  neutralMid: string;
  primary: string;
  primaryFill: string;
  primaryTransparent: string;
  surface: string;
  tooltipPaddingX: number;
  tooltipPaddingY: number;
  tooltipRadius: number;
}

export interface ChartLayout {
  compact: boolean;
  width: number;
}

export interface ChartKeyboardTarget {
  dataIndex: number;
  seriesIndex: number;
}

export type EChartsFigureEvent =
  | "blur"
  | "click"
  | "focus"
  | "keyboardactivate"
  | "keyboardclear"
  | "keyboardmove"
  | "mouseout"
  | "mouseover";

interface EChartsFigureProps {
  ariaDescribedBy?: string;
  ariaLabel: string;
  className?: string;
  createOption: (
    palette: ChartPalette,
    reducedMotion: boolean,
    layout: ChartLayout,
  ) => EChartsCoreOption;
  keyboardTargets?: readonly ChartKeyboardTarget[];
  onEvent?: (event: EChartsFigureEvent, params: unknown) => void;
  style?: CSSProperties;
}

function cssColor(probe: HTMLElement, name: string): string {
  probe.style.color = `var(${name})`;
  return getComputedStyle(probe).color;
}

function cssVariable(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function cssNumber(name: string): number {
  return Number.parseFloat(cssVariable(name));
}

function readPalette(): ChartPalette {
  const probe = document.createElement("span");
  probe.hidden = true;
  document.body.append(probe);
  const palette = {
    accent: cssColor(probe, "--chart-accent"),
    axisLine: cssColor(probe, "--chart-axis-line"),
    axisText: cssColor(probe, "--chart-axis-text"),
    compactBreakpoint: cssNumber("--chart-compact-breakpoint"),
    dataNeutralMedium: cssColor(probe, "--chart-data-neutral-medium"),
    dataNeutralSoft: cssColor(probe, "--chart-data-neutral-soft"),
    dataNeutralStrong: cssColor(probe, "--chart-data-neutral-strong"),
    fontFamily: cssVariable("--chart-font-family"),
    grid: cssColor(probe, "--chart-grid"),
    hoverSurface: cssColor(probe, "--chart-hover-surface"),
    label: cssColor(probe, "--chart-label"),
    labelFontSize: cssNumber("--chart-label-font-size"),
    metaFontSize: cssNumber("--chart-meta-font-size"),
    neutral: cssColor(probe, "--chart-neutral"),
    neutralFaint: cssColor(probe, "--chart-neutral-faint"),
    neutralMid: cssColor(probe, "--chart-neutral-mid"),
    primary: cssColor(probe, "--chart-primary"),
    primaryFill: cssColor(probe, "--chart-primary-fill"),
    primaryTransparent: cssColor(probe, "--chart-primary-transparent"),
    surface: cssColor(probe, "--chart-surface"),
    tooltipPaddingX: cssNumber("--chart-tooltip-padding-x"),
    tooltipPaddingY: cssNumber("--chart-tooltip-padding-y"),
    tooltipRadius: cssNumber("--chart-tooltip-radius"),
  };
  probe.remove();
  return palette;
}

function readLayout(host: HTMLElement, palette: ChartPalette): ChartLayout {
  const width = Math.max(host.clientWidth, 1);
  return {
    compact: width <= palette.compactBreakpoint,
    width,
  };
}

export function EChartsFigure({
  ariaDescribedBy,
  ariaLabel,
  className,
  createOption,
  keyboardTargets = [],
  onEvent,
  style,
}: EChartsFigureProps) {
  const chartRef = useRef<EChartsType | null>(null);
  const createOptionRef = useRef(createOption);
  const eventRef = useRef(onEvent);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const keyboardIndexRef = useRef(0);
  const keyboardTargetsRef = useRef(keyboardTargets);

  createOptionRef.current = createOption;
  eventRef.current = onEvent;
  keyboardTargetsRef.current = keyboardTargets;

  const showKeyboardTarget = (
    eventName: "focus" | "keyboardactivate" | "keyboardmove",
    index: number,
  ) => {
    const chart = chartRef.current;
    const targets = keyboardTargetsRef.current;
    const target = targets[index];
    if (!chart || !target) {
      return;
    }
    keyboardIndexRef.current = index;
    chart.dispatchAction({ type: "downplay" });
    chart.dispatchAction({ type: "highlight", ...target });
    chart.dispatchAction({ type: "showTip", ...target });
    eventRef.current?.(eventName, target);
  };

  const clearKeyboardTarget = (eventName: "blur" | "keyboardclear") => {
    const chart = chartRef.current;
    const target = keyboardTargetsRef.current[keyboardIndexRef.current];
    chart?.dispatchAction({ type: "downplay" });
    chart?.dispatchAction({ type: "hideTip" });
    eventRef.current?.(eventName, target ?? {});
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const targets = keyboardTargetsRef.current;
    if (targets.length === 0) {
      return;
    }

    const lastIndex = targets.length - 1;
    let nextIndex = keyboardIndexRef.current;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = Math.max(0, nextIndex - 1);
    } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = Math.min(lastIndex, nextIndex + 1);
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = lastIndex;
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      showKeyboardTarget("keyboardactivate", keyboardIndexRef.current);
      return;
    } else if (event.key === "Escape") {
      event.preventDefault();
      clearKeyboardTarget("keyboardclear");
      return;
    } else {
      return;
    }

    event.preventDefault();
    showKeyboardTarget("keyboardmove", nextIndex);
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return undefined;
    }

    const chart = init(host, undefined, { renderer: "svg" });
    chartRef.current = chart;
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let lastCompact: boolean | null = null;
    const render = () => {
      const palette = readPalette();
      const layout = readLayout(host, palette);
      lastCompact = layout.compact;
      chart.setOption(
        createOptionRef.current(palette, motionQuery.matches, layout),
        { notMerge: true },
      );
      host.setAttribute("aria-label", ariaLabel);
    };
    const forward = (event: "click" | "mouseout" | "mouseover") => (
      params: unknown,
    ) => {
      const payload = params as Partial<ChartKeyboardTarget>;
      if (typeof payload.dataIndex === "number" && typeof payload.seriesIndex === "number") {
        const index = keyboardTargetsRef.current.findIndex(
          (target) =>
            target.dataIndex === payload.dataIndex &&
            target.seriesIndex === payload.seriesIndex,
        );
        if (index >= 0) {
          keyboardIndexRef.current = index;
        }
      }
      eventRef.current?.(event, params);
    };
    const handlers = {
      click: forward("click"),
      mouseout: forward("mouseout"),
      mouseover: forward("mouseover"),
    };

    render();
    chart.on("click", handlers.click);
    chart.on("mouseout", handlers.mouseout);
    chart.on("mouseover", handlers.mouseover);

    const resizeObserver = new ResizeObserver(() => {
      chart.resize();
      const palette = readPalette();
      const compact = readLayout(host, palette).compact;
      if (compact !== lastCompact) {
        render();
      }
    });
    resizeObserver.observe(host);
    const themeObserver = new MutationObserver(render);
    themeObserver.observe(document.documentElement, {
      attributeFilter: ["data-theme"],
      attributes: true,
    });
    motionQuery.addEventListener("change", render);

    return () => {
      motionQuery.removeEventListener("change", render);
      themeObserver.disconnect();
      resizeObserver.disconnect();
      chart.off("click", handlers.click);
      chart.off("mouseout", handlers.mouseout);
      chart.off("mouseover", handlers.mouseover);
      chart.dispose();
      chartRef.current = null;
    };
  }, [ariaLabel]);

  useEffect(() => {
    const chart = chartRef.current;
    const host = hostRef.current;
    if (!chart || !host) {
      return;
    }
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const palette = readPalette();
    chart.setOption(
      createOption(palette, reducedMotion, readLayout(host, palette)),
      { notMerge: true },
    );
    host.setAttribute("aria-label", ariaLabel);
  }, [ariaLabel, createOption]);

  return (
    <div
      aria-describedby={ariaDescribedBy}
      aria-keyshortcuts={
        keyboardTargets.length > 0
          ? "ArrowLeft ArrowRight ArrowUp ArrowDown Home End Enter Escape"
          : undefined
      }
      aria-label={ariaLabel}
      className={className}
      onBlur={() => clearKeyboardTarget("blur")}
      onFocus={() => showKeyboardTarget("focus", keyboardIndexRef.current)}
      onKeyDown={handleKeyDown}
      ref={hostRef}
      role="img"
      style={style}
      tabIndex={0}
    />
  );
}
