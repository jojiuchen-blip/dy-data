import { useMemo, useState } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type {
  SalesCycleDistributionRow,
  SalesTrendRow,
} from "../../types/dashboard";
import { formatInteger } from "../../utils/format";
import { ResourcePanel } from "../ResourceState";
import {
  EChartsFigure,
  type ChartPalette,
} from "./EChartsFigure";

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
  seriesName?: string;
};

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

function monthlyOption(
  rows: SalesTrendRow[],
  palette: ChartPalette,
  reducedMotion: boolean,
): EChartsCoreOption {
  const months = rows.map((row) => row.month);
  const maxOrders = Math.max(1, ...rows.map((row) => row.order_count));

  // Direct adaptation of lieflat-charts G8 Rainfall Dual Area.
  // Only dy-data data, copy and semantic chart colors differ from the source.
  return {
    animationDuration: reducedMotion ? 0 : 1200,
    animationEasing: "quarticOut",
    aria: { enabled: true },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      lineStyle: { color: palette.axis, type: "dashed" },
    },
    grid: [
      { height: "26%", left: 44, right: 14, top: 8 },
      { bottom: 26, left: 44, right: 14, top: "42%" },
    ],
    tooltip: {
      backgroundColor: palette.neutral,
      borderWidth: 0,
      extraCssText: "border-radius:8px;box-shadow:none;",
      padding: [10, 14],
      textStyle: {
        color: palette.surface,
        fontFamily: "system-ui, sans-serif",
        fontSize: 12,
      },
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
          fontFamily: "system-ui, sans-serif",
          fontSize: 10,
          fontWeight: 600,
          interval: rows.length > 8 ? 1 : 0,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        data: months,
        gridIndex: 1,
        type: "category",
      },
    ],
    yAxis: [
      {
        axisLabel: {
          color: palette.label,
          fontFamily: "system-ui, sans-serif",
          fontSize: 9,
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
          color: palette.label,
          fontFamily: "system-ui, sans-serif",
          fontSize: 10,
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
          color: palette.neutralFaint,
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
  if (!row || !params.seriesName) {
    return null;
  }
  const isOrder = params.seriesName === "下单量";
  return {
    id: `${row.month}-${isOrder ? "orders" : "verified"}`,
    label: isOrder ? "下单量" : "核销量",
    month: row.month,
    series: isOrder ? "orders" : "verified",
    value: isOrder ? row.order_count : row.verify_order_count,
  };
}

export function MonthlyRainfallChart({ rows }: { rows: SalesTrendRow[] }) {
  const [hoveredPoint, setHoveredPoint] = useState<MonthlyChartPoint | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<MonthlyChartPoint | null>(null);
  const createOption = useMemo(
    () => (palette: ChartPalette, reducedMotion: boolean) =>
      monthlyOption(rows, palette, reducedMotion),
    [rows],
  );
  const activePoint = hoveredPoint ?? selectedPoint;

  if (rows.length === 0) {
    return <ResourcePanel>当前筛选下暂无月度趋势数据。</ResourcePanel>;
  }

  return (
    <div className="sales-chart-frame">
      <EChartsFigure
        ariaLabel="月度下单与核销趋势。上方雨柱为下单量，下方流线为核销量。"
        className="sales-echart sales-echart--rainfall"
        createOption={createOption}
        onEvent={(event, rawParams) => {
          const point = monthlyPointFromEvent(rawParams as ChartEventParams, rows);
          if (event === "mouseout") {
            setHoveredPoint(null);
          } else if (event === "mouseover") {
            setHoveredPoint(point);
          } else if (event === "click" && point) {
            setSelectedPoint((current) =>
              current?.id === point.id ? null : point,
            );
          }
        }}
      />
      <div className="sales-chart-inspector" aria-live="polite">
        {activePoint ? (
          <>
            <strong>{activePoint.month}</strong>
            <span>{activePoint.label}</span>
            <b>{formatInteger(activePoint.value)} 单</b>
            {selectedPoint?.id === activePoint.id ? <em>已锁定</em> : null}
          </>
        ) : (
          <span>悬浮图表查看月份明细；点击数据可锁定提示</span>
        )}
      </div>
    </div>
  );
}

function cycleOption(
  rows: SalesCycleDistributionRow[],
  palette: ChartPalette,
  reducedMotion: boolean,
): EChartsCoreOption {
  const maxDays = Math.max(
    1,
    ...rows.map((row) => Math.max(row.max_days ?? 0, 0)),
  );
  const rowColors = [
    palette.primary,
    palette.neutral,
    palette.neutralMid,
    palette.neutralFaint,
    palette.axis,
  ];
  const points = rows.flatMap((row, rowIndex) =>
    row.sample_points.map((point, pointIndex) => [
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

  // Direct adaptation of lieflat-charts G15 Jitter Strip.
  // The point geometry is preserved; each point now maps to a real order record.
  return {
    animationDelay: (dataIndex: number) => {
      const rowIndex = Math.round(Number(points[dataIndex]?.[1] ?? 0));
      return reducedMotion ? 0 : rowIndex * 260 + (dataIndex % 37) * 9;
    },
    animationDuration: reducedMotion ? 0 : 450,
    animationEasing: "cubicOut",
    aria: { enabled: true },
    grid: { bottom: 30, left: 118, right: 16, top: 14 },
    tooltip: {
      backgroundColor: palette.neutral,
      borderWidth: 0,
      extraCssText: "border-radius:8px;box-shadow:none;",
      padding: [10, 14],
      textStyle: {
        color: palette.surface,
        fontFamily: "system-ui, sans-serif",
        fontSize: 12,
      },
      formatter: (rawParams: unknown) => {
        const params = rawParams as { value?: unknown[] };
        const value = params.value ?? [];
        return `${String(value[3] ?? "")}<br/>${String(value[2] ?? "")} · ${formatDays(Number(value[0] ?? 0))}`;
      },
    },
    xAxis: {
      axisLabel: {
        color: palette.label,
        fontFamily: "system-ui, sans-serif",
        fontSize: 10,
        formatter: (value: number) => `${value} 天`,
      },
      axisLine: { show: false },
      axisTick: { show: false },
      max: maxDays,
      min: 0,
      name: "核销周期（天）",
      nameLocation: "middle",
      nameTextStyle: {
        color: palette.axis,
        fontFamily: "system-ui, sans-serif",
        fontSize: 8.5,
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
          opacity: 0.62,
        },
        name: "订单样本",
        symbolSize: 7,
        type: "scatter",
      },
      {
        data: rows.map((row, rowIndex) => ({
          label: {
            color: palette.neutral,
            fontFamily: "system-ui, sans-serif",
            fontSize: 10,
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

function cyclePointFromEvent(params: ChartEventParams): CycleChartFocus | null {
  if (params.seriesName !== "订单样本" || !Array.isArray(params.data)) {
    return null;
  }
  const value = params.data as unknown[];
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
  const [hoveredFocus, setHoveredFocus] = useState<CycleChartFocus | null>(null);
  const [selectedFocus, setSelectedFocus] = useState<CycleChartFocus | null>(null);
  const createOption = useMemo(
    () => (palette: ChartPalette, reducedMotion: boolean) =>
      cycleOption(rows, palette, reducedMotion),
    [rows],
  );
  const activeFocus = hoveredFocus ?? selectedFocus;

  if (rows.length === 0) {
    return <ResourcePanel>当前筛选下暂无已核销订单周期数据。</ResourcePanel>;
  }

  return (
    <div className="sales-chart-frame">
      <EChartsFigure
        ariaLabel="不同商品类型的核销周期点阵。每个点代表一笔真实订单。"
        className="sales-echart sales-echart--jitter"
        createOption={createOption}
        onEvent={(event, rawParams) => {
          const point = cyclePointFromEvent(rawParams as ChartEventParams);
          if (event === "mouseout") {
            setHoveredFocus(null);
          } else if (event === "mouseover") {
            setHoveredFocus(point);
          } else if (event === "click" && point) {
            setSelectedFocus((current) =>
              current?.id === point.id ? null : point,
            );
          }
        }}
        style={{ height: Math.max(320, rows.length * 64 + 64) }}
      />
      <div className="sales-chart-inspector" aria-live="polite">
        {activeFocus?.kind === "point" ? (
          <>
            <strong>{activeFocus.productType}</strong>
            <span>{activeFocus.orderId}</span>
            <b>{formatDays(activeFocus.cycleDays)}</b>
            {selectedFocus?.id === activeFocus.id ? <em>已锁定</em> : null}
          </>
        ) : (
          <span>悬浮订单点查看核销周期；点击数据可锁定提示</span>
        )}
      </div>
    </div>
  );
}
