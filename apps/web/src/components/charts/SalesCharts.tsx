import { useId, useMemo, useState } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type {
  SalesCycleDistributionRow,
  SalesTrendRow,
} from "../../types/dashboard";
import { formatInteger } from "../../utils/format";
import { ResourcePanel } from "../ResourceState";
import {
  EChartsFigure,
  type ChartKeyboardTarget,
  type ChartLayout,
  type ChartPalette,
  type EChartsFigureEvent,
} from "./EChartsFigure";

export interface ChartCandidateMetadata {
  approvedAdaptations: readonly string[];
  businessMapping: string;
  candidateId: string;
  candidateName: string;
  collection: "basics" | "glance" | "lupi";
  sourceFile: string;
}

const GLANCE_SOURCE = "docs/design-system/chart-gallery/glance-gallery.html";

export const MONTHLY_RAINFALL_CANDIDATE: ChartCandidateMetadata = {
  approvedAdaptations: [
    "business data",
    "Chinese copy",
    "dy-data semantic chart colors",
    "compact month-label interval",
  ],
  businessMapping: "MonthlyRainfallChart",
  candidateId: "G8",
  candidateName: "Rainfall Dual Area",
  collection: "glance",
  sourceFile: GLANCE_SOURCE,
};

export const CYCLE_JITTER_CANDIDATE: ChartCandidateMetadata = {
  approvedAdaptations: [
    "business data",
    "Chinese copy",
    "dy-data semantic chart colors",
    "localized category labels within the original plot geometry",
  ],
  businessMapping: "CycleJitterChart",
  candidateId: "G15",
  candidateName: "Jitter Strip",
  collection: "glance",
  sourceFile: GLANCE_SOURCE,
};

type MonthlyChartPoint = {
  id: string;
  label: string;
  month: string;
  series: "orders" | "verified";
  value: number;
};

type CycleChartFocus = {
  id: string;
  kind: "point";
  cycleDays: number;
  orderId: string;
  productType: string;
};

type ChartEventParams = {
  data?: unknown;
  dataIndex?: number;
  seriesIndex?: number;
  seriesName?: string;
};

type CycleChartDatum = [number, number, string, string, number];

function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)} 天`;
}

function deterministicJitter(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 1000) / 999 - 0.5;
}

function tooltipStyle(palette: ChartPalette) {
  return {
    backgroundColor: palette.neutral,
    borderWidth: 0,
    extraCssText: `border-radius:${palette.tooltipRadius}px;box-shadow:none;`,
    padding: [palette.tooltipPaddingY, palette.tooltipPaddingX],
    textStyle: {
      color: palette.surface,
      fontFamily: palette.fontFamily,
      fontSize: palette.labelFontSize,
    },
  };
}

function monthlyOption(
  rows: SalesTrendRow[],
  palette: ChartPalette,
  reducedMotion: boolean,
  layout: ChartLayout,
): EChartsCoreOption {
  const months = rows.map((row) => row.month);
  const maxOrders = Math.max(1, ...rows.map((row) => row.order_count));
  const monthLabelInterval = layout.compact
    ? Math.max(1, Math.ceil(rows.length / 5) - 1)
    : rows.length > 8
      ? 1
      : 0;

  return {
    animationDuration: reducedMotion ? 0 : 1200,
    animationEasing: "quarticOut",
    aria: { enabled: false },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      lineStyle: { color: palette.axisLine, type: "dashed" },
    },
    grid: [
      { height: "26%", left: 44, right: 14, top: 8 },
      { bottom: 30, left: 44, right: 14, top: "42%" },
    ],
    tooltip: {
      ...tooltipStyle(palette),
      trigger: "axis",
      formatter: (rawParams: unknown) => {
        const params = rawParams as Array<{ dataIndex?: number }>;
        const index = params[0]?.dataIndex ?? 0;
        const row = rows[index];
        if (!row) {
          return "";
        }
        return `${row.month}<br/>下单 ${formatInteger(row.order_count)} 单<br/>核销 ${formatInteger(row.verify_order_count)} 单`;
      },
    },
    xAxis: [
      {
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        data: months,
        gridIndex: 0,
        type: "category",
      },
      {
        axisLabel: {
          color: palette.label,
          fontFamily: palette.fontFamily,
          fontSize: palette.labelFontSize,
          fontWeight: 600,
          interval: monthLabelInterval,
        },
        axisLine: { lineStyle: { color: palette.axisLine }, show: false },
        axisTick: { show: false },
        data: months,
        gridIndex: 1,
        type: "category",
      },
    ],
    yAxis: [
      {
        axisLabel: {
          color: palette.axisText,
          fontFamily: palette.fontFamily,
          fontSize: palette.metaFontSize,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        gridIndex: 0,
        inverse: true,
        max: maxOrders,
        min: 0,
        splitLine: { show: false },
        type: "value",
      },
      {
        axisLabel: {
          color: palette.axisText,
          fontFamily: palette.fontFamily,
          fontSize: palette.metaFontSize,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        gridIndex: 1,
        splitLine: { lineStyle: { color: palette.grid } },
        type: "value",
      },
    ],
    series: [
      {
        barWidth: "55%",
        data: rows.map((row) => row.order_count),
        itemStyle: {
          borderRadius: [0, 0, 4, 4],
          color: palette.dataNeutralSoft,
        },
        name: "下单量",
        type: "bar",
        xAxisIndex: 0,
        yAxisIndex: 0,
      },
      {
        areaStyle: {
          color: {
            colorStops: [
              { color: palette.primaryFill, offset: 0 },
              { color: palette.primaryTransparent, offset: 1 },
            ],
            type: "linear",
            x: 0,
            x2: 0,
            y: 0,
            y2: 1,
          },
        },
        data: rows.map((row) => row.verify_order_count),
        lineStyle: { color: palette.primary, width: 2.2 },
        name: "核销量",
        showSymbol: false,
        smooth: 0.4,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
      },
    ],
  };
}

function monthlyPointFromEvent(
  params: ChartEventParams,
  rows: SalesTrendRow[],
): MonthlyChartPoint | null {
  const index = params.dataIndex ?? -1;
  const row = rows[index];
  const seriesIndex = params.seriesIndex ?? (params.seriesName === "核销量" ? 1 : 0);
  if (!row || (seriesIndex !== 0 && seriesIndex !== 1)) {
    return null;
  }
  const isOrder = seriesIndex === 0;
  return {
    id: `${row.month}-${isOrder ? "orders" : "verified"}`,
    label: isOrder ? "下单量" : "核销量",
    month: row.month,
    series: isOrder ? "orders" : "verified",
    value: isOrder ? row.order_count : row.verify_order_count,
  };
}

function applyPointEvent<T extends { id: string }>(
  event: EChartsFigureEvent,
  point: T | null,
  setHovered: (point: T | null) => void,
  setSelected: (updater: (current: T | null) => T | null) => void,
) {
  if (event === "mouseout" || event === "blur") {
    setHovered(null);
  } else if (event === "mouseover" || event === "focus" || event === "keyboardmove") {
    setHovered(point);
  } else if ((event === "click" || event === "keyboardactivate") && point) {
    setSelected((current) => (current?.id === point.id ? null : point));
    setHovered(point);
  } else if (event === "keyboardclear") {
    setHovered(null);
    setSelected(() => null);
  }
}

export function MonthlyRainfallChart({ rows }: { rows: SalesTrendRow[] }) {
  const descriptionId = useId();
  const summaryId = useId();
  const [hoveredPoint, setHoveredPoint] = useState<MonthlyChartPoint | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<MonthlyChartPoint | null>(null);
  const createOption = useMemo(
    () => (palette: ChartPalette, reducedMotion: boolean, layout: ChartLayout) =>
      monthlyOption(rows, palette, reducedMotion, layout),
    [rows],
  );
  const keyboardTargets = useMemo<ChartKeyboardTarget[]>(
    () => rows.flatMap((_, dataIndex) => [
      { dataIndex, seriesIndex: 0 },
      { dataIndex, seriesIndex: 1 },
    ]),
    [rows],
  );
  const activePoint = hoveredPoint ?? selectedPoint;

  if (rows.length === 0) {
    return <ResourcePanel>当前筛选下暂无月度趋势数据。</ResourcePanel>;
  }

  return (
    <div
      className="sales-chart-frame"
      data-chart-candidate={`${MONTHLY_RAINFALL_CANDIDATE.collection}-${MONTHLY_RAINFALL_CANDIDATE.candidateId}`}
    >
      <p className="visually-hidden" id={descriptionId}>
        使用方向键浏览月份与指标，回车键锁定当前数据，Esc 键清除锁定。
      </p>
      <ul className="visually-hidden" id={summaryId}>
        {rows.map((row) => (
          <li key={row.month}>
            {row.month}：下单 {formatInteger(row.order_count)} 单，核销 {formatInteger(row.verify_order_count)} 单。
          </li>
        ))}
      </ul>
      <EChartsFigure
        ariaDescribedBy={`${descriptionId} ${summaryId}`}
        ariaLabel="月度下单与核销趋势图"
        className="sales-echart sales-echart--rainfall"
        createOption={createOption}
        keyboardTargets={keyboardTargets}
        onEvent={(event, rawParams) => {
          applyPointEvent(
            event,
            monthlyPointFromEvent(rawParams as ChartEventParams, rows),
            setHoveredPoint,
            setSelectedPoint,
          );
        }}
      />
      <div
        aria-atomic="true"
        aria-live="polite"
        className="sales-chart-inspector"
        role="status"
      >
        {activePoint ? (
          <>
            <strong>{activePoint.month}</strong>
            <span>{activePoint.label}</span>
            <b>{formatInteger(activePoint.value)} 单</b>
            {selectedPoint?.id === activePoint.id ? <em>已锁定</em> : null}
          </>
        ) : (
          <span>悬浮或使用方向键查看月份明细；点击或按回车键可锁定数据</span>
        )}
      </div>
    </div>
  );
}

function createCyclePoints(rows: SalesCycleDistributionRow[]): CycleChartDatum[] {
  return rows.flatMap((row, rowIndex) =>
    row.sample_points.map<CycleChartDatum>((point, pointIndex) => [
      point.cycle_days,
      rowIndex +
        deterministicJitter(
          `${row.product_type}:${point.order_id}:${pointIndex}`,
        ) *
          0.58,
      point.order_id,
      row.product_type,
      rowIndex,
    ]),
  );
}

function cycleOption(
  rows: SalesCycleDistributionRow[],
  points: CycleChartDatum[],
  palette: ChartPalette,
  reducedMotion: boolean,
  _layout: ChartLayout,
): EChartsCoreOption {
  const maxDays = Math.max(
    1,
    ...rows.map((row) => Math.max(row.max_days ?? 0, 0)),
  );
  const rowColors = [
    palette.primary,
    palette.dataNeutralStrong,
    palette.dataNeutralMedium,
    palette.dataNeutralSoft,
    palette.accent,
  ];

  return {
    animationDelay: (dataIndex: number) => {
      const rowIndex = Math.round(Number(points[dataIndex]?.[1] ?? 0));
      return reducedMotion ? 0 : rowIndex * 260 + (dataIndex % 37) * 9;
    },
    animationDuration: reducedMotion ? 0 : 450,
    animationEasing: "cubicOut",
    aria: { enabled: false },
    grid: { bottom: 34, left: 86, right: 16, top: 14 },
    tooltip: {
      ...tooltipStyle(palette),
      formatter: (rawParams: unknown) => {
        const params = rawParams as { value?: unknown[] };
        const value = params.value ?? [];
        return `${String(value[3] ?? "")}<br/>订单 ${String(value[2] ?? "")} · ${formatDays(Number(value[0] ?? 0))}`;
      },
    },
    xAxis: {
      axisLabel: {
        color: palette.axisText,
        fontFamily: palette.fontFamily,
        fontSize: palette.metaFontSize,
        formatter: (value: number) => `${value} 天`,
      },
      axisLine: { lineStyle: { color: palette.axisLine }, show: false },
      axisTick: { show: false },
      max: maxDays,
      min: 0,
      name: "核销周期（天）",
      nameLocation: "middle",
      nameTextStyle: {
        color: palette.axisText,
        fontFamily: palette.fontFamily,
        fontSize: palette.metaFontSize,
      },
      splitLine: { lineStyle: { color: palette.grid } },
      type: "value",
    },
    yAxis: {
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      inverse: true,
      max: rows.length - 0.4,
      min: -0.6,
      splitLine: { show: false },
      type: "value",
    },
    series: [
      {
        data: points,
        itemStyle: {
          color: (params: { value?: unknown[] }) => {
            const rowIndex = Number(params.value?.[4] ?? 0);
            return rowColors[rowIndex % rowColors.length];
          },
        },
        name: "订单样本",
        symbolSize: 8,
        type: "scatter",
      },
      {
        data: rows.map((row, rowIndex) => ({
          label: {
            color: palette.dataNeutralStrong,
            fontFamily: palette.fontFamily,
            fontSize: palette.metaFontSize,
            fontWeight: 700,
            formatter: row.product_type,
            offset: [-8, 0],
            position: "left",
            show: true,
          },
          value: [0, rowIndex],
        })),
        name: "商品类型",
        silent: true,
        symbolSize: 0,
        type: "scatter",
      },
    ],
  };
}

function cyclePointFromEvent(
  params: ChartEventParams,
  points: CycleChartDatum[],
): CycleChartFocus | null {
  if ((params.seriesIndex ?? 0) !== 0) {
    return null;
  }
  const value = Array.isArray(params.data)
    ? (params.data as unknown[])
    : points[params.dataIndex ?? -1];
  if (!value) {
    return null;
  }
  const cycleDays = Number(value[0]);
  const orderId = String(value[2] ?? "");
  const productType = String(value[3] ?? "");
  if (!Number.isFinite(cycleDays) || !orderId || !productType) {
    return null;
  }
  return {
    cycleDays,
    id: `point-${productType}-${orderId}`,
    kind: "point",
    orderId,
    productType,
  };
}

export function CycleJitterChart({
  rows,
}: {
  rows: SalesCycleDistributionRow[];
}) {
  const descriptionId = useId();
  const summaryId = useId();
  const [hoveredFocus, setHoveredFocus] = useState<CycleChartFocus | null>(null);
  const [selectedFocus, setSelectedFocus] = useState<CycleChartFocus | null>(null);
  const points = useMemo(() => createCyclePoints(rows), [rows]);
  const createOption = useMemo(
    () => (palette: ChartPalette, reducedMotion: boolean, layout: ChartLayout) =>
      cycleOption(rows, points, palette, reducedMotion, layout),
    [points, rows],
  );
  const keyboardTargets = useMemo<ChartKeyboardTarget[]>(
    () => points.map((_, dataIndex) => ({ dataIndex, seriesIndex: 0 })),
    [points],
  );
  const activeFocus = hoveredFocus ?? selectedFocus;

  if (rows.length === 0) {
    return <ResourcePanel>当前筛选下暂无已核销订单周期数据。</ResourcePanel>;
  }

  return (
    <div
      className="sales-chart-frame"
      data-chart-candidate={`${CYCLE_JITTER_CANDIDATE.collection}-${CYCLE_JITTER_CANDIDATE.candidateId}`}
    >
      <p className="visually-hidden" id={descriptionId}>
        使用方向键浏览订单样本，回车键锁定当前数据，Esc 键清除锁定。
      </p>
      <ul className="visually-hidden" id={summaryId}>
        {rows.map((row) => (
          <li key={row.product_type}>
            {row.product_type}：{formatInteger(row.count)} 笔，周期范围 {formatDays(row.min_days)}至{formatDays(row.max_days)}，中位数 {formatDays(row.median_days)}。
          </li>
        ))}
      </ul>
      <EChartsFigure
        ariaDescribedBy={`${descriptionId} ${summaryId}`}
        ariaLabel="不同商品类型核销周期分布图"
        className="sales-echart sales-echart--jitter"
        createOption={createOption}
        keyboardTargets={keyboardTargets}
        onEvent={(event, rawParams) => {
          applyPointEvent(
            event,
            cyclePointFromEvent(rawParams as ChartEventParams, points),
            setHoveredFocus,
            setSelectedFocus,
          );
        }}
        style={{ height: Math.max(320, rows.length * 64 + 64) }}
      />
      <div
        aria-atomic="true"
        aria-live="polite"
        className="sales-chart-inspector"
        role="status"
      >
        {activeFocus?.kind === "point" ? (
          <>
            <strong>{activeFocus.productType}</strong>
            <span>{activeFocus.orderId}</span>
            <b>{formatDays(activeFocus.cycleDays)}</b>
            {selectedFocus?.id === activeFocus.id ? <em>已锁定</em> : null}
          </>
        ) : (
          <span>悬浮或使用方向键查看订单周期；点击或按回车键可锁定数据</span>
        )}
      </div>
    </div>
  );
}
