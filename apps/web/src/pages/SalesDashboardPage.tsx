import { useMemo, useState } from "react";
import { fetchFilterMeta, fetchSalesDashboard } from "../api/client";
import { DefinitionList } from "../components/DefinitionList";
import { FilterBar, FilterField } from "../components/Filters";
import { SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import {
  ResourceNotice,
  ResourcePanel,
  resourceSourceLabel,
} from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  FilterMetaData,
  SalesCycleDistributionRow,
  SalesTrendRow,
  StoreOption,
} from "../types/dashboard";
import {
  formatCurrency,
  formatInteger,
  formatPercent,
} from "../utils/format";
import { defaultProductType, productOptions, storeOptions } from "../utils/options";

interface SalesDashboardPageProps {
  searchParams: URLSearchParams;
}

const ALL_MONTHS = "all";
const chartWidth = 960;
const chartLeft = 168;
const chartRight = 68;
const chartTop = 30;
const chartBottom = 38;
const chartRowHeight = 58;

function availableMonths(meta: FilterMetaData | undefined): string[] {
  const months = [
    ...new Set([...(meta?.sale_months ?? []), ...(meta?.verify_months ?? [])]),
  ]
    .filter(Boolean)
    .sort();
  return months;
}

function monthOptions(meta: FilterMetaData | undefined, activeMonth: string) {
  const months = availableMonths(meta).reverse();
  const options = [
    { value: ALL_MONTHS, label: "全年" },
    ...months.map((month) => ({ value: month, label: month })),
  ];
  if (
    activeMonth &&
    activeMonth !== ALL_MONTHS &&
    !options.some((option) => option.value === activeMonth)
  ) {
    options.splice(1, 0, { value: activeMonth, label: activeMonth });
  }
  return options;
}

function trendMonthsForPeriod(
  meta: FilterMetaData | undefined,
  activeMonth: string,
): string[] {
  if (activeMonth && activeMonth !== ALL_MONTHS) {
    return [activeMonth];
  }
  return availableMonths(meta);
}

function selectedStore(
  meta: FilterMetaData | undefined,
  storeId: string,
): StoreOption | undefined {
  if (!storeId) {
    return undefined;
  }
  return (
    meta?.stores.find((store) => store.store_id === storeId) ?? {
      store_id: storeId,
      store_name: storeId,
    }
  );
}

function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)} 天`;
}

function cycleAxisValue(value: number | null): number {
  return Math.max(value ?? 0, 0);
}

function truncateLabel(value: string): string {
  return value.length > 12 ? `${value.slice(0, 11)}...` : value;
}

function MonthlyOrderVerifyChart({ rows }: { rows: SalesTrendRow[] }) {
  if (rows.length === 0) {
    return <ResourcePanel>当前筛选下暂无月度趋势数据。</ResourcePanel>;
  }

  const width = 960;
  const height = 270;
  const left = 64;
  const right = 34;
  const top = 34;
  const bottom = 44;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maxValue = Math.max(
    1,
    ...rows.flatMap((row) => [row.order_count, row.verify_order_count]),
  );
  const xForIndex = (index: number) =>
    rows.length === 1
      ? left + plotWidth / 2
      : left + (index / (rows.length - 1)) * plotWidth;
  const yForValue = (value: number) =>
    top + plotHeight - (value / maxValue) * plotHeight;
  const linePath = (selector: (row: SalesTrendRow) => number) =>
    rows
      .map(
        (row, index) =>
          `${index === 0 ? "M" : "L"} ${xForIndex(index)} ${yForValue(selector(row))}`,
      )
      .join(" ");
  const areaPath = (selector: (row: SalesTrendRow) => number) => {
    const baseline = top + plotHeight;
    const points = rows
      .map((row, index) => `${xForIndex(index)} ${yForValue(selector(row))}`)
      .join(" L ");
    return `M ${xForIndex(0)} ${baseline} L ${points} L ${xForIndex(
      rows.length - 1,
    )} ${baseline} Z`;
  };
  const ticks = [0, maxValue / 3, (maxValue * 2) / 3, maxValue];

  return (
    <div className="sales-monthly-chart-wrap">
      <svg
        aria-label="月度下单与核销趋势"
        className="sales-monthly-chart"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        {ticks.map((tick) => {
          const y = yForValue(tick);
          return (
            <g key={tick}>
              <line
                className="sales-monthly-chart__grid"
                x1={left}
                x2={width - right}
                y1={y}
                y2={y}
              />
              <text
                className="sales-monthly-chart__tick"
                textAnchor="end"
                x={left - 12}
                y={y + 5}
              >
                {formatInteger(Math.round(tick))}
              </text>
            </g>
          );
        })}
        <path
          className="sales-monthly-chart__area sales-monthly-chart__area--orders"
          d={areaPath((row) => row.order_count)}
        />
        <path
          className="sales-monthly-chart__area sales-monthly-chart__area--verified"
          d={areaPath((row) => row.verify_order_count)}
        />
        <path
          className="sales-monthly-chart__line sales-monthly-chart__line--orders"
          d={linePath((row) => row.order_count)}
        />
        <path
          className="sales-monthly-chart__line sales-monthly-chart__line--verified"
          d={linePath((row) => row.verify_order_count)}
        />
        {rows.map((row, index) => {
          const x = xForIndex(index);
          return (
            <g key={row.month}>
              <circle
                className="sales-monthly-chart__dot sales-monthly-chart__dot--orders"
                cx={x}
                cy={yForValue(row.order_count)}
                r={4}
              >
                <title>
                  {row.month} 下单量 {formatInteger(row.order_count)}
                </title>
              </circle>
              <circle
                className="sales-monthly-chart__dot sales-monthly-chart__dot--verified"
                cx={x}
                cy={yForValue(row.verify_order_count)}
                r={4}
              >
                <title>
                  {row.month} 核销量 {formatInteger(row.verify_order_count)}
                </title>
              </circle>
              <text
                className="sales-monthly-chart__month"
                textAnchor="middle"
                x={x}
                y={height - 10}
              >
                {row.month}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function CycleDistributionChart({ rows }: { rows: SalesCycleDistributionRow[] }) {
  if (rows.length === 0) {
    return <ResourcePanel>当前筛选下暂无已核销订单周期数据。</ResourcePanel>;
  }

  const maxDays = Math.max(
    1,
    ...rows.map((row) => cycleAxisValue(row.max_days)),
  );
  const chartHeight = chartTop + chartBottom + rows.length * chartRowHeight;
  const plotWidth = chartWidth - chartLeft - chartRight;
  const valueX = (value: number | null) =>
    chartLeft + (cycleAxisValue(value) / maxDays) * plotWidth;
  const ticks = [0, maxDays / 2, maxDays];

  return (
    <div className="sales-cycle-chart-wrap">
      <svg
        aria-label="核销周期分布"
        className="sales-cycle-chart"
        role="img"
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
      >
        <line
          className="sales-cycle-chart__axis"
          x1={chartLeft}
          x2={chartWidth - chartRight}
          y1={chartHeight - chartBottom}
          y2={chartHeight - chartBottom}
        />
        {ticks.map((tick) => {
          const x = valueX(tick);
          return (
            <g key={tick}>
              <line
                className="sales-cycle-chart__grid"
                x1={x}
                x2={x}
                y1={chartTop - 10}
                y2={chartHeight - chartBottom}
              />
              <text
                className="sales-cycle-chart__tick"
                textAnchor="middle"
                x={x}
                y={chartHeight - 12}
              >
                {formatDays(tick)}
              </text>
            </g>
          );
        })}
        {rows.map((row, rowIndex) => {
          const y = chartTop + rowIndex * chartRowHeight + chartRowHeight / 2;
          const minX = valueX(row.min_days);
          const q1X = valueX(row.q1_days);
          const medianX = valueX(row.median_days);
          const q3X = valueX(row.q3_days);
          const maxX = valueX(row.max_days);
          return (
            <g key={row.product_type}>
              <text
                className="sales-cycle-chart__label"
                textAnchor="end"
                x={chartLeft - 16}
                y={y + 5}
              >
                {truncateLabel(row.product_type)}
                <title>{row.product_type}</title>
              </text>
              <line
                className="sales-cycle-chart__range"
                x1={minX}
                x2={maxX}
                y1={y}
                y2={y}
              />
              <rect
                className="sales-cycle-chart__box"
                height={18}
                rx={4}
                width={Math.max(q3X - q1X, 2)}
                x={q1X}
                y={y - 9}
              />
              <line
                className="sales-cycle-chart__median"
                x1={medianX}
                x2={medianX}
                y1={y - 12}
                y2={y + 12}
              />
              {row.sample_points.map((point, pointIndex) => (
                <circle
                  className="sales-cycle-chart__point"
                  cx={valueX(point.cycle_days)}
                  cy={y + ((pointIndex % 5) - 2) * 3}
                  key={`${point.order_id}-${pointIndex}`}
                  r={3}
                >
                  <title>
                    {point.order_id} · {formatDays(point.cycle_days)}
                  </title>
                </circle>
              ))}
              <text
                className="sales-cycle-chart__count"
                x={chartWidth - chartRight + 12}
                y={y + 5}
              >
                {formatInteger(row.count)} 单
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function SalesDashboardPage({ searchParams }: SalesDashboardPageProps) {
  const [storeId, setStoreId] = useState(searchParams.get("store_id") ?? "");
  const [month, setMonth] = useState(searchParams.get("month") ?? ALL_MONTHS);
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "",
  );

  const metaResource = useApiResource(fetchFilterMeta, []);
  const meta = metaResource.data?.data;
  const activeStoreId = storeId || meta?.stores[0]?.store_id || "";
  const activeStore = selectedStore(meta, activeStoreId);
  const activeMonth = month || ALL_MONTHS;
  const periodLabel = activeMonth === ALL_MONTHS ? "全年" : activeMonth;
  const activeProductType = productType || defaultProductType(meta);
  const trendMonths = useMemo(
    () => trendMonthsForPeriod(meta, activeMonth),
    [meta, activeMonth],
  );
  const salesResource = useApiResource(
    () =>
      fetchSalesDashboard({
        store: activeStore as StoreOption,
        month: activeMonth,
        productType: activeProductType,
        trendMonths,
      }),
    [activeStore?.store_id, activeMonth, activeProductType, trendMonths.join("|")],
    { enabled: Boolean(activeStore) },
  );

  const dashboard = salesResource.data?.data;
  const definitions = salesResource.data?.definitions ?? [];
  const definitionFor = (key: string): string | undefined =>
    definitions.find((definition) => definition.key === key)?.description;
  const metrics = dashboard?.metrics ?? {
    total_sales_order_count: 0,
    self_verify_order_count: 0,
    self_verify_rate: 0,
    total_verify_order_count: 0,
    actual_verify_amount_cent: 0,
    avg_verify_cycle_days: null,
  };

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <h1>核销表现</h1>
        </div>
        <span className="source-pill">
          {resourceSourceLabel(salesResource.data, salesResource.loading)}
        </span>
      </section>

      <ResourceNotice
        fallbackReason={
          salesResource.data?.fallbackReason ?? metaResource.data?.fallbackReason
        }
        loading={salesResource.loading || metaResource.loading}
        error={salesResource.error ?? metaResource.error}
      />

      <FilterBar>
        <FilterField label="门店搜索">
          <SearchableStoreSelect
            options={storeOptions(meta, activeStore)}
            placeholder="输入门店名称"
            value={activeStoreId}
            onChange={setStoreId}
          />
        </FilterField>
        <SelectField
          label="月份"
          onChange={setMonth}
          options={monthOptions(meta, activeMonth)}
          value={activeMonth}
        />
        <SelectField
          label="商品类型"
          onChange={setProductType}
          options={productOptions(meta, activeProductType)}
          value={activeProductType}
        />
      </FilterBar>

      {!activeStore ? (
        <ResourcePanel>请先选择门店。</ResourcePanel>
      ) : !dashboard && salesResource.loading ? (
        <ResourcePanel>正在加载核销表现数据...</ResourcePanel>
      ) : !dashboard ? (
        <ResourcePanel tone="error">核销表现数据暂不可用。</ResourcePanel>
      ) : (
        <>
          <section className="metric-grid metric-grid--sales">
            <MetricCard
              description={definitionFor("total_sales_order_count")}
              label="总销售订单量"
              meta={`${dashboard.store.store_name} · ${periodLabel}`}
              value={formatInteger(metrics.total_sales_order_count)}
            />
            <MetricCard
              description={definitionFor("self_verify_order_count")}
              label="自店核销数"
              meta="销售门店与核销门店一致"
              tone="blue"
              value={formatInteger(metrics.self_verify_order_count)}
            />
            <MetricCard
              description={definitionFor("self_verify_rate")}
              label="自店核销率"
              meta="自店核销数 / 总销售订单量"
              tone="amber"
              value={formatPercent(metrics.self_verify_rate)}
            />
            <MetricCard
              description={definitionFor("total_verify_order_count")}
              label="实际核销总数"
              meta={`${dashboard.store.store_name} · ${periodLabel}`}
              tone="blue"
              value={formatInteger(metrics.total_verify_order_count)}
            />
            <MetricCard
              description={definitionFor("actual_verify_amount_cent")}
              label="实际核销金额"
              meta="不含核销后退款"
              value={formatCurrency(metrics.actual_verify_amount_cent)}
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>月度下单与核销趋势</h2>
                <p>按下单月份统计；下单量不含支付取消。</p>
              </div>
              <div className="sales-monthly-chart__legend" aria-label="趋势图图例">
                <span className="sales-monthly-chart__legend-item sales-monthly-chart__legend-item--orders">
                  下单量
                </span>
                <span className="sales-monthly-chart__legend-item sales-monthly-chart__legend-item--verified">
                  核销量
                </span>
              </div>
            </div>
            <MonthlyOrderVerifyChart rows={dashboard.trend_rows} />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>核销周期分布</h2>
                <p>箱线图 + 散点，按商品类型展示</p>
              </div>
            </div>
            <CycleDistributionChart rows={dashboard.cycle_rows} />
          </section>

        </>
      )}

      <DefinitionList
        definitions={definitions}
        extra={[
          {
            key: "sales_month_filter",
            label: "月份筛选口径",
            description:
              "默认展示全年数据；选择具体月份后，总销售订单量、自店核销数、自店核销率按 sale_time 归属月份统计，实际核销总数、实际核销金额和核销周期按 verify_time 归属月份统计。",
          },
          {
            key: "order_deduplication",
            label: "订单去重口径",
            description:
              "订单数相关指标统一按 order_id 去重；一单核销多券时，实际核销总数仍只计 1 单。",
          },
        ]}
        title="本页计算口径"
      />
    </div>
  );
}
