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
import {
  CycleJitterChart,
  MonthlyRainfallChart,
} from "../components/charts/SalesCharts";
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

function trendFigureTitle(rows: SalesTrendRow[]): string {
  if (rows.length < 2) {
    return "当前月份下单量与核销量对比";
  }
  const current = rows[rows.length - 1];
  const previous = rows[rows.length - 2];
  const direction =
    current.verify_order_count > previous.verify_order_count
      ? "回升"
      : current.verify_order_count < previous.verify_order_count
        ? "回落"
        : "保持稳定";
  const relation =
    current.verify_order_count < current.order_count
      ? "仍低于下单量"
      : current.verify_order_count > current.order_count
        ? "高于下单量"
        : "与下单量持平";
  return `最新月份核销量${direction}，${relation}`;
}

function cycleFigureTitle(rows: SalesCycleDistributionRow[]): string {
  if (rows.length === 0) {
    return "不同商品类型的核销周期分布";
  }
  const widest = rows.reduce((current, row) => {
    const currentRange =
      cycleAxisValue(current.max_days) - cycleAxisValue(current.min_days);
    const rowRange = cycleAxisValue(row.max_days) - cycleAxisValue(row.min_days);
    return rowRange > currentRange ? row : current;
  });
  return `${widest.product_type}核销周期波动最大`;
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

          <div className="sales-chart-gallery">
            <section className="content-section chart-figure-runtime">
              <div className="section-title chart-figure-runtime__head">
                <div>
                  <span className="chart-figure-runtime__eyebrow">
                    运营快读 · 月度趋势
                  </span>
                  <h2>{trendFigureTitle(dashboard.trend_rows)}</h2>
                  <p>上方雨柱为下单量，橙色流线为核销量 · 按下单月份统计</p>
                </div>
              </div>
              <MonthlyRainfallChart rows={dashboard.trend_rows} />
              <p className="sales-chart-source">
                双区趋势 · 订单与核销明细 · 下单量不含支付取消
              </p>
            </section>

            <section className="content-section chart-figure-runtime">
              <div className="section-title chart-figure-runtime__head">
                <div>
                  <span className="chart-figure-runtime__eyebrow">
                    分析细读 · 周期分布
                  </span>
                  <h2>{cycleFigureTitle(dashboard.cycle_rows)}</h2>
                  <p>每个点代表一笔真实订单 · 横向位置表示核销周期</p>
                </div>
              </div>
              <CycleJitterChart rows={dashboard.cycle_rows} />
              <p className="sales-chart-source">
                抖动点阵 · 已核销订单 · 核销时间减去销售时间
              </p>
            </section>
          </div>

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
