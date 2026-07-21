import { useMemo, useState, type KeyboardEvent } from "react";
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
  AdminUser,
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
import {
  defaultProductType,
  productOptionsForScope,
  productScopeOptions,
  storeOptions,
} from "../utils/options";

interface SalesDashboardPageProps {
  currentUser: AdminUser;
  searchParams: URLSearchParams;
}

const ALL_MONTHS = "all";
const ALL_STORES_OPTION: StoreOption = {
  store_id: "",
  store_name: "全部门店",
};
const chartWidth = 960;
const chartLeft = 168;
const chartRight = 68;
const chartTop = 30;
const chartBottom = 38;
const chartRowHeight = 58;
const cycleBoxHeight = 16;
const cycleMedianHeight = 26;
const cycleWhiskerCapHeight = 16;
const cyclePointRadius = 2.4;

type MonthlyChartPoint = {
  id: string;
  label: string;
  month: string;
  series: "orders" | "verified";
  value: number;
};

type CycleChartFocus =
  | {
      id: string;
      kind: "row";
      count: number;
      maxDays: number | null;
      medianDays: number | null;
      minDays: number | null;
      productType: string;
      q1Days: number | null;
      q3Days: number | null;
    }
  | {
      id: string;
      kind: "point";
      cycleDays: number;
      orderId: string;
      productType: string;
    };

function handleSvgActivation(
  event: KeyboardEvent<SVGGElement>,
  callback: () => void,
) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  event.preventDefault();
  callback();
}

function availableMonths(meta: FilterMetaData | undefined): string[] {
  const months = [
    ...new Set([...(meta?.sale_months ?? []), ...(meta?.verify_months ?? [])]),
  ]
    .filter(Boolean)
    .sort();
  return months;
}

function availableSaleMonths(meta: FilterMetaData | undefined): string[] {
  return [...new Set(meta?.sale_months ?? [])].filter(Boolean).sort();
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
  return availableSaleMonths(meta);
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

function canViewAllStores(currentUser: AdminUser): boolean {
  return currentUser.store_scope_mode === "all";
}

function defaultStoreIdForUser(
  meta: FilterMetaData | undefined,
  currentUser: AdminUser,
): string {
  if (canViewAllStores(currentUser)) {
    return "";
  }
  return currentUser.store_ids[0] ?? meta?.stores[0]?.store_id ?? "";
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
  const [hoveredPoint, setHoveredPoint] = useState<MonthlyChartPoint | null>(
    null,
  );
  const [selectedPoint, setSelectedPoint] = useState<MonthlyChartPoint | null>(
    null,
  );

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
  const activePoint = hoveredPoint ?? selectedPoint;
  const togglePoint = (point: MonthlyChartPoint) => {
    setSelectedPoint((current) => (current?.id === point.id ? null : point));
  };
  const renderPoint = (point: MonthlyChartPoint, x: number, y: number) => {
    const isSelected = selectedPoint?.id === point.id;
    const isActive = activePoint?.id === point.id;

    return (
      <g
        aria-label={`${point.month} ${point.label} ${formatInteger(point.value)}`}
        aria-pressed={isSelected}
        className={[
          "sales-monthly-chart__point",
          isActive ? "is-active" : "",
          isSelected ? "is-selected" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        key={point.id}
        onBlur={() => setHoveredPoint(null)}
        onClick={() => togglePoint(point)}
        onFocus={() => setHoveredPoint(point)}
        onKeyDown={(event) => handleSvgActivation(event, () => togglePoint(point))}
        onMouseEnter={() => setHoveredPoint(point)}
        onMouseLeave={() => setHoveredPoint(null)}
        role="button"
        tabIndex={0}
      >
        <circle
          className={`sales-monthly-chart__dot sales-monthly-chart__dot--${point.series}`}
          cx={x}
          cy={y}
          r={3.2}
        >
          <title>
            {point.month} {point.label} {formatInteger(point.value)}
          </title>
        </circle>
      </g>
    );
  };

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
          const orderPoint: MonthlyChartPoint = {
            id: `${row.month}-orders`,
            label: "下单量",
            month: row.month,
            series: "orders",
            value: row.order_count,
          };
          const verifiedPoint: MonthlyChartPoint = {
            id: `${row.month}-verified`,
            label: "核销量",
            month: row.month,
            series: "verified",
            value: row.verify_order_count,
          };
          return (
            <g key={row.month}>
              {renderPoint(orderPoint, x, yForValue(row.order_count))}
              {renderPoint(verifiedPoint, x, yForValue(row.verify_order_count))}
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
      <div className="sales-chart-inspector" aria-live="polite">
        {activePoint ? (
          <>
            <strong>{activePoint.month}</strong>
            <span>{activePoint.label}</span>
            <b>{formatInteger(activePoint.value)}</b>
            {selectedPoint?.id === activePoint.id ? <em>已锁定</em> : null}
          </>
        ) : (
          <span>悬浮或点击数据点查看明细</span>
        )}
      </div>
    </div>
  );
}

function CycleDistributionChart({ rows }: { rows: SalesCycleDistributionRow[] }) {
  const [hoveredFocus, setHoveredFocus] = useState<CycleChartFocus | null>(null);
  const [selectedFocus, setSelectedFocus] = useState<CycleChartFocus | null>(
    null,
  );

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
  const activeFocus = hoveredFocus ?? selectedFocus;
  const toggleFocus = (focus: CycleChartFocus) => {
    setSelectedFocus((current) => (current?.id === focus.id ? null : focus));
  };

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
          const boxWidth = Math.max(q3X - q1X, 6);
          const boxX =
            q3X - q1X < 6 ? (q1X + q3X) / 2 - boxWidth / 2 : q1X;
          const rowFocus: CycleChartFocus = {
            id: `row-${row.product_type}`,
            count: row.count,
            kind: "row",
            maxDays: row.max_days,
            medianDays: row.median_days,
            minDays: row.min_days,
            productType: row.product_type,
            q1Days: row.q1_days,
            q3Days: row.q3_days,
          };
          const isRowActive = activeFocus?.id === rowFocus.id;
          const isRowSelected = selectedFocus?.id === rowFocus.id;
          return (
            <g
              aria-label={`${row.product_type} ${formatInteger(row.count)} 单，中位数 ${formatDays(row.median_days)}`}
              aria-pressed={isRowSelected}
              className={[
                "sales-cycle-chart__row",
                isRowActive ? "is-active" : "",
                isRowSelected ? "is-selected" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={row.product_type}
              onBlur={() => setHoveredFocus(null)}
              onClick={() => toggleFocus(rowFocus)}
              onFocus={() => setHoveredFocus(rowFocus)}
              onKeyDown={(event) =>
                handleSvgActivation(event, () => toggleFocus(rowFocus))
              }
              onMouseEnter={() => setHoveredFocus(rowFocus)}
              onMouseLeave={() => setHoveredFocus(null)}
              role="button"
              tabIndex={0}
            >
              <rect
                className="sales-cycle-chart__row-band"
                height={chartRowHeight - 18}
                rx={8}
                width={plotWidth}
                x={chartLeft}
                y={y - chartRowHeight / 2 + 9}
              />
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
              <line
                className="sales-cycle-chart__whisker"
                x1={minX}
                x2={minX}
                y1={y - cycleWhiskerCapHeight / 2}
                y2={y + cycleWhiskerCapHeight / 2}
              />
              <line
                className="sales-cycle-chart__whisker"
                x1={maxX}
                x2={maxX}
                y1={y - cycleWhiskerCapHeight / 2}
                y2={y + cycleWhiskerCapHeight / 2}
              />
              <rect
                className="sales-cycle-chart__box"
                height={cycleBoxHeight}
                rx={5}
                width={boxWidth}
                x={boxX}
                y={y - cycleBoxHeight / 2}
              />
              <line
                className="sales-cycle-chart__median"
                x1={medianX}
                x2={medianX}
                y1={y - cycleMedianHeight / 2}
                y2={y + cycleMedianHeight / 2}
              />
              {row.sample_points.map((point, pointIndex) => {
                const pointFocus: CycleChartFocus = {
                  id: `point-${row.product_type}-${point.order_id}-${pointIndex}`,
                  cycleDays: point.cycle_days,
                  kind: "point",
                  orderId: point.order_id,
                  productType: row.product_type,
                };
                const isPointActive = activeFocus?.id === pointFocus.id;
                const isPointSelected = selectedFocus?.id === pointFocus.id;

                return (
                  <g
                    aria-label={`${row.product_type} 订单 ${point.order_id} ${formatDays(point.cycle_days)}`}
                    aria-pressed={isPointSelected}
                    className={[
                      "sales-cycle-chart__sample",
                      isPointActive ? "is-active" : "",
                      isPointSelected ? "is-selected" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    key={pointFocus.id}
                    onBlur={(event) => {
                      event.stopPropagation();
                      setHoveredFocus(null);
                    }}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleFocus(pointFocus);
                    }}
                    onFocus={(event) => {
                      event.stopPropagation();
                      setHoveredFocus(pointFocus);
                    }}
                    onKeyDown={(event) => {
                      event.stopPropagation();
                      handleSvgActivation(event, () => toggleFocus(pointFocus));
                    }}
                    onMouseEnter={(event) => {
                      event.stopPropagation();
                      setHoveredFocus(pointFocus);
                    }}
                    onMouseLeave={(event) => {
                      event.stopPropagation();
                      setHoveredFocus(null);
                    }}
                    role="button"
                    tabIndex={0}
                  >
                    <circle
                      className="sales-cycle-chart__point"
                      cx={valueX(point.cycle_days)}
                      cy={y}
                      r={cyclePointRadius}
                    />
                    <title>
                      {point.order_id} · {formatDays(point.cycle_days)}
                    </title>
                  </g>
                );
              })}
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
      <div className="sales-chart-inspector" aria-live="polite">
        {activeFocus?.kind === "row" ? (
          <>
            <strong>{activeFocus.productType}</strong>
            <span>{formatInteger(activeFocus.count)} 单</span>
            <span>最小 {formatDays(activeFocus.minDays)}</span>
            <span>Q1 {formatDays(activeFocus.q1Days)}</span>
            <span>中位 {formatDays(activeFocus.medianDays)}</span>
            <span>Q3 {formatDays(activeFocus.q3Days)}</span>
            <span>最大 {formatDays(activeFocus.maxDays)}</span>
            {selectedFocus?.id === activeFocus.id ? <em>已锁定</em> : null}
          </>
        ) : activeFocus?.kind === "point" ? (
          <>
            <strong>{activeFocus.productType}</strong>
            <span>{activeFocus.orderId}</span>
            <b>{formatDays(activeFocus.cycleDays)}</b>
            {selectedFocus?.id === activeFocus.id ? <em>已锁定</em> : null}
          </>
        ) : (
          <span>悬浮或点击箱体、须线或样本点查看明细</span>
        )}
      </div>
    </div>
  );
}

export function SalesDashboardPage({
  currentUser,
  searchParams,
}: SalesDashboardPageProps) {
  const [storeId, setStoreId] = useState(searchParams.get("store_id") ?? "");
  const [month, setMonth] = useState(searchParams.get("month") ?? ALL_MONTHS);
  const [productScope, setProductScope] = useState(
    searchParams.get("product_scope") ?? "",
  );
  const [productType, setProductType] = useState(
    searchParams.get("product_type") ?? "",
  );

  const metaResource = useApiResource(fetchFilterMeta, []);
  const meta = metaResource.data?.data;
  const allowAllStores = canViewAllStores(currentUser);
  const activeStoreId = storeId || defaultStoreIdForUser(meta, currentUser);
  const activeStore = activeStoreId
    ? selectedStore(meta, activeStoreId)
    : allowAllStores
      ? ALL_STORES_OPTION
      : undefined;
  const activeMonth = month || ALL_MONTHS;
  const periodLabel = activeMonth === ALL_MONTHS ? "全年" : activeMonth;
  const activeProductScope = productScope || ALL_MONTHS;
  const activeProductType =
    productType ||
    (activeProductScope === ALL_MONTHS ? defaultProductType(meta) : ALL_MONTHS);
  const handleProductScopeChange = (value: string) => {
    setProductScope(value);
    setProductType(ALL_MONTHS);
  };
  const trendMonths = useMemo(
    () => trendMonthsForPeriod(meta, activeMonth),
    [meta, activeMonth],
  );
  const salesResource = useApiResource(
    () =>
      fetchSalesDashboard({
        store: activeStore as StoreOption,
        month: activeMonth,
        productScope: activeProductScope,
        productType: activeProductType,
        trendMonths,
      }),
    [
      activeStore?.store_id,
      activeMonth,
      activeProductScope,
      activeProductType,
      trendMonths.join("|"),
    ],
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
            allowEmpty={allowAllStores}
            emptyLabel="全部门店"
            options={storeOptions(
              meta,
              activeStoreId ? activeStore : undefined,
            )}
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
          label="产品范围"
          onChange={handleProductScopeChange}
          options={productScopeOptions(meta, activeProductScope)}
          value={activeProductScope}
        />
        <SelectField
          label="商品类型"
          onChange={setProductType}
          options={productOptionsForScope(
            meta,
            activeProductScope,
            activeProductType,
          )}
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
              value={formatInteger(metrics.self_verify_order_count)}
            />
            <MetricCard
              description={definitionFor("self_verify_rate")}
              label="自店核销率"
              meta="自店核销数 / 总销售订单量"
              value={formatPercent(metrics.self_verify_rate)}
            />
            <MetricCard
              description={definitionFor("total_verify_order_count")}
              label="实际核销总数"
              meta={`${dashboard.store.store_name} · ${periodLabel}`}
              value={formatInteger(metrics.total_verify_order_count)}
            />
            <MetricCard
              description={definitionFor("actual_verify_amount_cent")}
              label="实际核销金额"
              meta="不含核销后退款"
              value={formatCurrency(metrics.actual_verify_amount_cent)}
            />
            <MetricCard
              description={definitionFor("avg_verify_cycle_days")}
              label="平均核销周期"
              meta="从销售时间到核销时间"
              value={formatDays(metrics.avg_verify_cycle_days)}
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
              "默认展示全年数据；选择具体月份后，总销售订单量、自店核销数和自店核销率按销售时间所在月份统计；实际核销总数、实际核销金额和核销周期按核销时间所在月份统计。",
          },
          {
            key: "order_deduplication",
            label: "订单去重口径",
            description:
              "订单数相关指标统一按订单编号去重；一单核销多券时，实际核销总数仍只计 1 单。",
          },
        ]}
        title="本页计算口径"
      />
    </div>
  );
}
