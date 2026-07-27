import { useEffect, useRef, type CSSProperties } from "react";
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
  axis: string;
  grid: string;
  hoverSurface: string;
  label: string;
  neutral: string;
  neutralFaint: string;
  neutralMid: string;
  primary: string;
  primaryFill: string;
  primaryTransparent: string;
  surface: string;
}

type EChartsFigureEvent = "click" | "mouseout" | "mouseover";

interface EChartsFigureProps {
  ariaLabel: string;
  className?: string;
  createOption: (palette: ChartPalette, reducedMotion: boolean) => EChartsCoreOption;
  onEvent?: (event: EChartsFigureEvent, params: unknown) => void;
  style?: CSSProperties;
}

function cssColor(probe: HTMLElement, name: string): string {
  probe.style.color = `var(${name})`;
  return getComputedStyle(probe).color;
}

function readPalette(): ChartPalette {
  const probe = document.createElement("span");
  probe.hidden = true;
  document.body.append(probe);
  const palette = {
    accent: cssColor(probe, "--chart-accent"),
    axis: cssColor(probe, "--chart-axis"),
    grid: cssColor(probe, "--chart-grid"),
    hoverSurface: cssColor(probe, "--chart-hover-surface"),
    label: cssColor(probe, "--chart-label"),
    neutral: cssColor(probe, "--chart-neutral"),
    neutralFaint: cssColor(probe, "--chart-neutral-faint"),
    neutralMid: cssColor(probe, "--chart-neutral-mid"),
    primary: cssColor(probe, "--chart-primary"),
    primaryFill: cssColor(probe, "--chart-primary-fill"),
    primaryTransparent: cssColor(probe, "--chart-primary-transparent"),
    surface: cssColor(probe, "--chart-surface"),
  };
  probe.remove();
  return palette;
}

export function EChartsFigure({
  ariaLabel,
  className,
  createOption,
  onEvent,
  style,
}: EChartsFigureProps) {
  const chartRef = useRef<EChartsType | null>(null);
  const createOptionRef = useRef(createOption);
  const eventRef = useRef(onEvent);
  const hostRef = useRef<HTMLDivElement | null>(null);

  createOptionRef.current = createOption;
  eventRef.current = onEvent;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return undefined;
    }

    const chart = init(host, undefined, { renderer: "svg" });
    chartRef.current = chart;
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const render = () => {
      chart.setOption(
        createOptionRef.current(readPalette(), motionQuery.matches),
        { notMerge: true },
      );
    };
    const forward = (event: EChartsFigureEvent) => (params: unknown) => {
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

    const resizeObserver = new ResizeObserver(() => chart.resize());
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
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    chart.setOption(createOption(readPalette(), reducedMotion), {
      notMerge: true,
    });
  }, [createOption]);

  return (
    <div
      aria-label={ariaLabel}
      className={className}
      ref={hostRef}
      role="img"
      style={style}
      tabIndex={0}
    />
  );
}
