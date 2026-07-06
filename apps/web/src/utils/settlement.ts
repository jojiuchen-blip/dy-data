import {
  commissionTablesResponse,
  defaultMonth,
  defaultStore,
  monthlySummaryResponse,
  orderDetails,
  storeRankingResponse,
} from "../data/mockData";
import type {
  DetailFilters,
  NonCommissionOrderRow,
  OrderDetail,
  PayableCommissionRow,
  ReceivableCommissionRow,
  SalesCycleDistributionRow,
  SalesCyclePoint,
  SalesDashboardData,
  SalesDashboardMetrics,
  SalesMetricRow,
  SalesTrendRow,
  SelectOption,
  SettlementViewData,
  StoreOption,
  StoreRankingRow,
  StoreRankingTotals,
} from "../types/dashboard";

const ALL_PRODUCTS = "all";
const ALL_MONTHS = "all";
const MS_PER_DAY = 24 * 60 * 60 * 1000;
const MAX_CYCLE_SAMPLE_POINTS = 90;

function matchesProduct(product: string, selected: string): boolean {
  return selected === ALL_PRODUCTS || product === selected;
}

function isBlank(value: string | undefined): boolean {
  return value === undefined || value === "" || value === ALL_PRODUCTS;
}

function addStore(map: Map<string, StoreOption>, id: string, name: string) {
  if (id && !map.has(id)) {
    map.set(id, { store_id: id, store_name: name || id });
  }
}

export function getStoreOptions(): SelectOption[] {
  const stores = new Map<string, StoreOption>();
  storeRankingResponse.data.rows.forEach((row) =>
    addStore(stores, row.store_id, row.store_name),
  );
  addStore(stores, defaultStore.store_id, defaultStore.store_name);
  orderDetails.forEach((row) => {
    addStore(stores, row.sale_store_id, row.sale_store_name);
    addStore(stores, row.verify_store_id, row.verify_store_name);
  });

  return [...stores.values()].map((store) => ({
    value: store.store_id,
    label: store.store_name,
  }));
}

export function getStoreName(storeId: string): string {
  return (
    getStoreOptions().find((store) => store.value === storeId)?.label ?? storeId
  );
}

export function getProductOptions(): SelectOption[] {
  const products = new Set<string>();
  commissionTablesResponse.data.tables.receivable_commissions.forEach((row) =>
    products.add(row.product_type),
  );
  commissionTablesResponse.data.tables.payable_commissions.forEach((row) =>
    products.add(row.product_type),
  );
  commissionTablesResponse.data.tables.non_commission_orders.forEach((row) =>
    products.add(row.product_type),
  );
  orderDetails.forEach((row) => products.add(row.product_type));

  return [
    { value: ALL_PRODUCTS, label: "全部产品" },
    ...[...products].sort((a, b) => a.localeCompare(b, "zh-CN")).map((value) => ({
      value,
      label: value,
    })),
  ];
}

export function getMonthOptions(): SelectOption[] {
  const months = new Set<string>([
    defaultMonth,
    monthlySummaryResponse.data.month,
    ...orderDetails.flatMap((row) => [row.sale_month, row.verify_month]),
  ]);

  return [...months]
    .filter(Boolean)
    .sort()
    .reverse()
    .map((month) => ({ value: month, label: month }));
}

export function getRankingRows(
  month: string,
  productType: string,
): StoreRankingRow[] {
  if (
    month === storeRankingResponse.data.month &&
    productType === storeRankingResponse.data.product_type
  ) {
    return storeRankingResponse.data.rows
      .slice(0, storeRankingResponse.data.limit)
      .map((row) => ({ ...row }));
  }

  return buildRankingRows(month, productType)
    .slice(0, 20)
    .map((row, index) => ({ ...row, rank: index + 1 }));
}

export function getRankingTotals(
  month: string,
  productType: string,
): StoreRankingTotals {
  if (
    month === storeRankingResponse.data.month &&
    productType === storeRankingResponse.data.product_type
  ) {
    return { ...storeRankingResponse.data.totals };
  }

  const rows = buildRankingRows(month, productType);
  return {
    sales_order_count: sum(rows, (row) => row.sales_order_count),
    self_verify_income_cent: sum(rows, (row) => row.self_verify_income_cent),
    effective_commission_income_cent: sum(
      rows,
      (row) => row.effective_commission_income_cent,
    ),
  };
}

function buildRankingRows(
  month: string,
  productType: string,
): StoreRankingRow[] {
  const rowsByStore = new Map<string, StoreRankingRow>();

  const ensure = (storeId: string, storeName: string): StoreRankingRow => {
    const existing = rowsByStore.get(storeId);
    if (existing) {
      return existing;
    }
    const row: StoreRankingRow = {
      rank: 0,
      store_id: storeId,
      store_name: storeName,
      sales_order_count: 0,
      self_sold_self_verified_count: 0,
      self_sold_other_verified_count: 0,
      other_sold_self_verified_count: 0,
      self_verify_income_cent: 0,
      effective_commission_income_cent: 0,
    };
    rowsByStore.set(storeId, row);
    return row;
  };

  orderDetails.forEach((detail) => {
    if (!matchesProduct(detail.product_type, productType)) {
      return;
    }

    if (detail.sale_month === month) {
      ensure(detail.sale_store_id, detail.sale_store_name).sales_order_count += 1;
    }

    if (!detail.is_verified || detail.verify_month !== month) {
      return;
    }

    const saleStore = ensure(detail.sale_store_id, detail.sale_store_name);
    const verifyStore = ensure(detail.verify_store_id, detail.verify_store_name);

    if (detail.sale_store_id === detail.verify_store_id) {
      saleStore.self_sold_self_verified_count += 1;
      saleStore.self_verify_income_cent += detail.paid_amount_cent;
      return;
    }

    saleStore.self_sold_other_verified_count += 1;
    saleStore.effective_commission_income_cent +=
      detail.receivable_commission_cent;
    verifyStore.other_sold_self_verified_count += 1;
    verifyStore.self_verify_income_cent += Math.max(
      detail.paid_amount_cent - detail.payable_commission_cent,
      0,
    );
  });

  return [...rowsByStore.values()]
    .sort(
      (a, b) =>
        b.sales_order_count - a.sales_order_count ||
        b.self_verify_income_cent - a.self_verify_income_cent,
    )
    .map((row, index) => ({ ...row, rank: index + 1 }));
}

function filterByProduct<T extends { product_type: string }>(
  rows: T[],
  productType: string,
): T[] {
  return productType === ALL_PRODUCTS
    ? rows.map((row) => ({ ...row }))
    : rows.filter((row) => row.product_type === productType).map((row) => ({ ...row }));
}

function sum<T>(rows: T[], selector: (row: T) => number): number {
  return rows.reduce((total, row) => total + selector(row), 0);
}

export function getSettlementView(
  storeId: string,
  month: string,
  productType: string,
): SettlementViewData {
  const isDefaultStore = storeId === defaultStore.store_id;
  const canUseContractMock =
    isDefaultStore && month === monthlySummaryResponse.data.month;

  if (canUseContractMock) {
    const tables = {
      receivable_commissions: filterByProduct(
        commissionTablesResponse.data.tables.receivable_commissions,
        productType,
      ),
      payable_commissions: filterByProduct(
        commissionTablesResponse.data.tables.payable_commissions,
        productType,
      ),
      non_commission_orders: filterByProduct(
        commissionTablesResponse.data.tables.non_commission_orders,
        productType,
      ),
    };

    const metrics =
      productType === ALL_PRODUCTS
        ? monthlySummaryResponse.data.metrics
        : {
            estimated_receivable_commission_cent: sum(
              tables.receivable_commissions,
              (row) => row.estimated_receivable_commission_cent,
            ),
            commissionable_total_cent: sum(
              tables.receivable_commissions,
              (row) => row.commissionable_total_cent,
            ),
            estimated_payable_commission_cent: sum(
              tables.payable_commissions,
              (row) => row.payable_commission_cent,
            ),
          };

    return {
      store: defaultStore,
      month,
      product_type: productType,
      metrics,
      tables,
      source: "contract-mock",
    };
  }

  return deriveSettlementFromDetails(storeId, month, productType);
}

function makeReceivableRow(productType: string): ReceivableCommissionRow {
  return {
    product_type: productType,
    verified_coupon_count: 0,
    paid_amount_cent: 0,
    commission_rate: 0,
    commissionable_total_cent: 0,
    estimated_receivable_commission_cent: 0,
  };
}

function makePayableRow(productType: string): PayableCommissionRow {
  return {
    product_type: productType,
    verified_coupon_count: 0,
    paid_amount_cent: 0,
    commission_rate: 0,
    payable_commission_cent: 0,
  };
}

function makeNonCommissionRow(productType: string): NonCommissionOrderRow {
  return {
    product_type: productType,
    verified_coupon_count: 0,
    paid_amount_cent: 0,
  };
}

function deriveSettlementFromDetails(
  storeId: string,
  month: string,
  productType: string,
): SettlementViewData {
  const receivable = new Map<string, ReceivableCommissionRow>();
  const payable = new Map<string, PayableCommissionRow>();
  const nonCommission = new Map<string, NonCommissionOrderRow>();

  const getReceivable = (type: string) => {
    const row = receivable.get(type) ?? makeReceivableRow(type);
    receivable.set(type, row);
    return row;
  };
  const getPayable = (type: string) => {
    const row = payable.get(type) ?? makePayableRow(type);
    payable.set(type, row);
    return row;
  };
  const getNonCommission = (type: string) => {
    const row = nonCommission.get(type) ?? makeNonCommissionRow(type);
    nonCommission.set(type, row);
    return row;
  };

  orderDetails.forEach((detail) => {
    if (!matchesProduct(detail.product_type, productType) || !detail.is_verified) {
      return;
    }

    const isVerifyMonth = detail.verify_month === month;
    const isCrossStore = detail.relation_type === "cross_store";

    if (
      isVerifyMonth &&
      isCrossStore &&
      detail.sale_store_id === storeId &&
      detail.is_commissionable
    ) {
      const row = getReceivable(detail.product_type);
      row.verified_coupon_count += 1;
      row.paid_amount_cent += detail.paid_amount_cent;
      row.commissionable_total_cent += detail.receivable_commission_cent;
      row.estimated_receivable_commission_cent += detail.receivable_commission_cent;
    }

    if (
      isVerifyMonth &&
      isCrossStore &&
      detail.verify_store_id === storeId &&
      detail.is_commissionable
    ) {
      const row = getPayable(detail.product_type);
      row.verified_coupon_count += 1;
      row.paid_amount_cent += detail.paid_amount_cent;
      row.payable_commission_cent += detail.payable_commission_cent;
    }

    if (
      isVerifyMonth &&
      detail.relation_type === "same_store" &&
      detail.sale_store_id === storeId &&
      detail.verify_store_id === storeId &&
      detail.is_commissionable === false
    ) {
      const row = getNonCommission(detail.product_type);
      row.verified_coupon_count += 1;
      row.paid_amount_cent += detail.paid_amount_cent;
    }
  });

  const receivableRows = [...receivable.values()].map((row) => ({
    ...row,
    commission_rate:
      row.paid_amount_cent > 0
        ? row.commissionable_total_cent / row.paid_amount_cent
        : 0,
  }));
  const payableRows = [...payable.values()].map((row) => ({
    ...row,
    commission_rate:
      row.paid_amount_cent > 0
        ? row.payable_commission_cent / row.paid_amount_cent
        : 0,
  }));

  return {
    store: {
      store_id: storeId,
      store_name: getStoreName(storeId),
    },
    month,
    product_type: productType,
    metrics: {
      estimated_receivable_commission_cent: sum(
        receivableRows,
        (row) => row.estimated_receivable_commission_cent,
      ),
      commissionable_total_cent: sum(
        receivableRows,
        (row) => row.commissionable_total_cent,
      ),
      estimated_payable_commission_cent: sum(
        payableRows,
        (row) => row.payable_commission_cent,
      ),
    },
    tables: {
      receivable_commissions: receivableRows,
      payable_commissions: payableRows,
      non_commission_orders: [...nonCommission.values()],
    },
    source: "detail-derived",
  };
}

export function filterOrderDetails(
  rows: OrderDetail[],
  filters: DetailFilters,
): OrderDetail[] {
  const query = filters.q?.trim().toLowerCase();

  return rows.filter((row) => {
    if (!isBlank(filters.product_type) && row.product_type !== filters.product_type) {
      return false;
    }
    if (!isBlank(filters.sale_store_id) && row.sale_store_id !== filters.sale_store_id) {
      return false;
    }
    if (
      !isBlank(filters.exclude_sale_store_id) &&
      row.sale_store_id === filters.exclude_sale_store_id
    ) {
      return false;
    }
    if (!isBlank(filters.sale_month) && row.sale_month !== filters.sale_month) {
      return false;
    }
    if (!isBlank(filters.is_verified) && String(row.is_verified) !== filters.is_verified) {
      return false;
    }
    if (!isBlank(filters.verify_store_id) && row.verify_store_id !== filters.verify_store_id) {
      return false;
    }
    if (
      !isBlank(filters.exclude_verify_store_id) &&
      row.verify_store_id === filters.exclude_verify_store_id
    ) {
      return false;
    }
    if (!isBlank(filters.verify_month) && row.verify_month !== filters.verify_month) {
      return false;
    }
    if (!isBlank(filters.relation_type) && row.relation_type !== filters.relation_type) {
      return false;
    }
    if (
      !isBlank(filters.is_commissionable) &&
      String(row.is_commissionable) !== filters.is_commissionable
    ) {
      return false;
    }
    if (
      query &&
      !row.order_id.toLowerCase().includes(query) &&
      !row.coupon_id.toLowerCase().includes(query)
    ) {
      return false;
    }
    return true;
  });
}

export function detailsHref(params: DetailFilters): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, value);
    }
  });
  return `/details?${search.toString()}`;
}

export function detailFiltersFromSearch(
  searchParams: URLSearchParams,
): DetailFilters {
  const filters: DetailFilters = {};
  [
    "product_type",
    "sale_store_id",
    "exclude_sale_store_id",
    "sale_month",
    "is_verified",
    "verify_store_id",
    "exclude_verify_store_id",
    "verify_month",
    "relation_type",
    "is_commissionable",
    "q",
  ].forEach((key) => {
    const value = searchParams.get(key);
    if (value) {
      filters[key as keyof DetailFilters] = value;
    }
  });
  return filters;
}

interface SalesDashboardBuildInput {
  rows: OrderDetail[];
  store: StoreOption;
  month: string;
  productType: string;
  trendMonths?: string[];
}

function monthFromDateTime(value: string | null | undefined): string {
  return value ? value.slice(0, 7) : "";
}

function matchesMonth(value: string | null | undefined, selected: string): boolean {
  return selected === ALL_MONTHS || !selected || monthFromDateTime(value) === selected;
}

function orderIdentity(row: OrderDetail): string {
  return row.order_id || row.coupon_id;
}

function validSalesRow(row: OrderDetail, productType: string): boolean {
  return matchesProduct(row.product_type, productType) && !row.is_refund_excluded;
}

function daysBetween(
  startValue: string | null | undefined,
  endValue: string | null | undefined,
): number | null {
  if (!startValue || !endValue) {
    return null;
  }
  const start = new Date(startValue);
  const end = new Date(endValue);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return null;
  }
  return Math.max((end.getTime() - start.getTime()) / MS_PER_DAY, 0);
}

function roundMetric(value: number): number {
  return Math.round(value * 100) / 100;
}

function percentile(sortedValues: number[], ratio: number): number | null {
  if (sortedValues.length === 0) {
    return null;
  }
  const position = (sortedValues.length - 1) * ratio;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) {
    return sortedValues[lower];
  }
  const weight = position - lower;
  return sortedValues[lower] * (1 - weight) + sortedValues[upper] * weight;
}

function sampleCyclePoints(points: SalesCyclePoint[]): SalesCyclePoint[] {
  if (points.length <= MAX_CYCLE_SAMPLE_POINTS) {
    return points;
  }
  const lastIndex = points.length - 1;
  return Array.from({ length: MAX_CYCLE_SAMPLE_POINTS }, (_, index) => {
    const sourceIndex = Math.round((index * lastIndex) / (MAX_CYCLE_SAMPLE_POINTS - 1));
    return points[sourceIndex];
  });
}

function salesMetricsFor(
  rows: OrderDetail[],
  storeId: string,
  month: string,
  productType: string,
): SalesDashboardMetrics {
  const salesOrders = new Set<string>();
  const selfVerifyOrders = new Set<string>();
  const verifyOrders = new Set<string>();
  const amountRows = new Set<string>();
  const cycleDaysByOrder = new Map<string, number>();
  let actualVerifyAmountCent = 0;

  rows.forEach((row) => {
    if (!validSalesRow(row, productType)) {
      return;
    }
    const orderId = orderIdentity(row);
    const isSaleMonth = matchesMonth(row.sale_time, month);
    const isVerifyMonth = matchesMonth(row.verify_time, month);

    if (row.sale_store_id === storeId && isSaleMonth) {
      salesOrders.add(orderId);
      if (row.is_verified && row.verify_store_id === storeId) {
        selfVerifyOrders.add(orderId);
      }
    }

    if (row.is_verified && row.verify_store_id === storeId && isVerifyMonth) {
      verifyOrders.add(orderId);
      const amountKey = row.coupon_id || `${orderId}:${row.verify_time}`;
      if (!amountRows.has(amountKey)) {
        amountRows.add(amountKey);
        actualVerifyAmountCent += row.paid_amount_cent;
      }

      const cycleDays = daysBetween(row.sale_time, row.verify_time);
      if (cycleDays !== null) {
        const current = cycleDaysByOrder.get(orderId);
        if (current === undefined || cycleDays < current) {
          cycleDaysByOrder.set(orderId, cycleDays);
        }
      }
    }
  });

  const cycleValues = [...cycleDaysByOrder.values()];
  return {
    total_sales_order_count: salesOrders.size,
    self_verify_order_count: selfVerifyOrders.size,
    self_verify_rate:
      salesOrders.size > 0 ? selfVerifyOrders.size / salesOrders.size : 0,
    total_verify_order_count: verifyOrders.size,
    actual_verify_amount_cent: actualVerifyAmountCent,
    avg_verify_cycle_days:
      cycleValues.length > 0
        ? roundMetric(sum(cycleValues, (value) => value) / cycleValues.length)
        : null,
  };
}

function productTypesForSalesView(
  rows: OrderDetail[],
  storeId: string,
  month: string,
  productType: string,
): string[] {
  const products = new Set<string>();
  rows.forEach((row) => {
    if (!validSalesRow(row, productType)) {
      return;
    }
    const inSaleMonth =
      row.sale_store_id === storeId && matchesMonth(row.sale_time, month);
    const inVerifyMonth =
      row.is_verified &&
      row.verify_store_id === storeId &&
      matchesMonth(row.verify_time, month);
    if (inSaleMonth || inVerifyMonth) {
      products.add(row.product_type);
    }
  });
  return [...products].sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function salesMetricRows(
  rows: OrderDetail[],
  storeId: string,
  month: string,
  productType: string,
): SalesMetricRow[] {
  return productTypesForSalesView(rows, storeId, month, productType).map(
    (type) => ({
      product_type: type,
      ...salesMetricsFor(rows, storeId, month, type),
    }),
  );
}

function salesTrendRows(
  rows: OrderDetail[],
  storeId: string,
  productType: string,
  months: string[],
): SalesTrendRow[] {
  return months.map((month) => {
    const orders = new Set<string>();
    const verifiedOrders = new Set<string>();

    rows.forEach((row) => {
      if (
        !validSalesRow(row, productType) ||
        monthFromDateTime(row.sale_time) !== month
      ) {
        return;
      }
      const orderId = orderIdentity(row);
      if (row.sale_store_id === storeId) {
        orders.add(orderId);
      }
      if (row.is_verified && row.verify_store_id === storeId) {
        verifiedOrders.add(orderId);
      }
    });

    return {
      month,
      order_count: orders.size,
      verify_order_count: verifiedOrders.size,
    };
  });
}

function salesCycleRows(
  rows: OrderDetail[],
  storeId: string,
  month: string,
  productType: string,
): SalesCycleDistributionRow[] {
  const byProduct = new Map<string, SalesCyclePoint[]>();
  const bestByOrder = new Map<string, SalesCyclePoint>();

  rows.forEach((row) => {
    if (
      !validSalesRow(row, productType) ||
      !row.is_verified ||
      row.verify_store_id !== storeId ||
      !matchesMonth(row.verify_time, month)
    ) {
      return;
    }

    const cycleDays = daysBetween(row.sale_time, row.verify_time);
    if (cycleDays === null) {
      return;
    }

    const orderId = orderIdentity(row);
    const point: SalesCyclePoint = {
      order_id: orderId,
      cycle_days: roundMetric(cycleDays),
      sale_time: row.sale_time,
      verify_time: row.verify_time,
    };
    const key = `${row.product_type}:${orderId}`;
    const current = bestByOrder.get(key);
    if (current === undefined || point.cycle_days < current.cycle_days) {
      bestByOrder.set(key, point);
    }
  });

  bestByOrder.forEach((point, key) => {
    const productTypeKey = key.split(":")[0] || "未映射";
    const points = byProduct.get(productTypeKey) ?? [];
    points.push(point);
    byProduct.set(productTypeKey, points);
  });

  return [...byProduct.entries()]
    .map(([type, points]) => {
      const sortedPoints = [...points].sort(
        (a, b) => a.cycle_days - b.cycle_days || a.order_id.localeCompare(b.order_id),
      );
      const values = sortedPoints.map((point) => point.cycle_days);
      return {
        product_type: type,
        count: values.length,
        min_days: roundMetric(values[0]),
        q1_days: roundMetric(percentile(values, 0.25) ?? values[0]),
        median_days: roundMetric(percentile(values, 0.5) ?? values[0]),
        q3_days: roundMetric(percentile(values, 0.75) ?? values[0]),
        max_days: roundMetric(values[values.length - 1]),
        avg_days: roundMetric(sum(values, (value) => value) / values.length),
        sample_points: sampleCyclePoints(sortedPoints),
      };
    })
    .sort((a, b) => b.count - a.count || a.product_type.localeCompare(b.product_type, "zh-CN"));
}

function uniqueOrderDetailRows(rows: OrderDetail[]): OrderDetail[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = row.coupon_id || `${row.order_id}:${row.sale_time}:${row.verify_time}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function monthsFromSalesRows(rows: OrderDetail[], storeId: string, productType: string): string[] {
  const months = new Set<string>();
  rows.forEach((row) => {
    if (!validSalesRow(row, productType) || row.sale_store_id !== storeId) {
      return;
    }
    const month = monthFromDateTime(row.sale_time);
    if (month) {
      months.add(month);
    }
  });
  return [...months].sort();
}

export function buildSalesDashboardView({
  rows,
  store,
  month,
  productType,
  trendMonths = [month],
}: SalesDashboardBuildInput): SalesDashboardData {
  const uniqueRows = uniqueOrderDetailRows(rows);
  const orderedTrendMonths = [
    ...new Set(trendMonths.filter((value) => value && value !== ALL_MONTHS)),
  ].sort();
  if (month !== ALL_MONTHS && month && !orderedTrendMonths.includes(month)) {
    orderedTrendMonths.unshift(month);
  }
  const effectiveTrendMonths =
    orderedTrendMonths.length > 0
      ? orderedTrendMonths
      : monthsFromSalesRows(uniqueRows, store.store_id, productType);

  return {
    store,
    month,
    product_type: productType,
    metrics: salesMetricsFor(uniqueRows, store.store_id, month, productType),
    product_rows: salesMetricRows(uniqueRows, store.store_id, month, productType),
    trend_rows: salesTrendRows(
      uniqueRows,
      store.store_id,
      productType,
      effectiveTrendMonths,
    ),
    cycle_rows: salesCycleRows(uniqueRows, store.store_id, month, productType),
    source_row_count: uniqueRows.length,
  };
}
