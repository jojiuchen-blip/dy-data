import { useEffect, useState } from "react";
import {
  fetchSettlementFilterMeta,
  fetchSettlementStoreRanking,
} from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { FieldInput, SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { TablePagination } from "../components/TablePagination";
import { usePublishedView } from "../hooks/usePublishedView";
import type {
  SettlementStoreRankingRow,
  RankingSortBy,
  StoreFinanceRankingBasis,
} from "../types/dashboard";
import { formatCurrency, formatInteger } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";

interface StoreRankingPageProps {
  searchParams: URLSearchParams;
}

const PAGE_SIZE = 20;
const displayMetricCurrency = (value: number | null | undefined) =>
  value === null ? "暂不可用" : value === undefined ? "暂无数据" : formatCurrency(value);
const displayMetricCount = (value: number | null | undefined, unit: string) =>
  value === null ? "暂不可用" : value === undefined ? "暂无数据" : `${formatInteger(value)} ${unit}`;

const RANKING_BASIS_OPTIONS: Array<{ value: StoreFinanceRankingBasis; label: string }> = [
  { value: "SALES_AMOUNT_CUMULATIVE", label: "销售金额（累计）" },
  { value: "VERIFIED_AMOUNT_CUMULATIVE", label: "核销金额（累计）" },
  { value: "PROMOTION_FEE_MONTH", label: "当期推广服务费" },
  { value: "PROMOTION_FEE_CUMULATIVE", label: "累计推广服务费" },
];

function rankingSortByForBasis(basis: StoreFinanceRankingBasis): RankingSortBy {
  if (basis === "SALES_AMOUNT_CUMULATIVE") return "SALES_AMOUNT";
  if (basis === "VERIFIED_AMOUNT_CUMULATIVE") return "VERIFIED_AMOUNT";
  return "PROMOTION_FEE";
}

export function StoreRankingPage({ searchParams }: StoreRankingPageProps) {
  const [periodKey, setPeriodKey] = useState(searchParams.get("periodKey") ?? "");
  const [productScope, setProductScope] = useState(
    searchParams.get("productScope") ?? "all",
  );
  const productType = searchParams.get("productType") ?? "";
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [page, setPage] = useState(1);
  const [rankingBasis, setRankingBasis] = useState<StoreFinanceRankingBasis>(() => {
    const requested = searchParams.get("rankingBasis");
    // A legacy cumulative view must start from this month's default basis.
    return searchParams.get("periodType") !== "CUMULATIVE" &&
      RANKING_BASIS_OPTIONS.some((option) => option.value === requested)
      ? requested as StoreFinanceRankingBasis : "PROMOTION_FEE_MONTH";
  });
  const sortBy = rankingSortByForBasis(rankingBasis);

  // Old bookmarks cannot restore cumulative request state. This page has no
  // persisted filter cache; keep the URL canonical for copied links as well.
  useEffect(() => {
    const url = new URL(window.location.href);
    const legacyCumulative = url.searchParams.get("periodType") === "CUMULATIVE";
    const fixed: Record<string, string> = { periodType: "MONTHLY" };
    if (legacyCumulative) Object.assign(fixed, { rankingBasis: "PROMOTION_FEE_MONTH", sortBy: "PROMOTION_FEE", sortOrder: "DESC" });
    let changed = false;
    Object.entries(fixed).forEach(([key, value]) => {
      if (url.searchParams.has(key) && url.searchParams.get(key) !== value) {
        url.searchParams.set(key, value);
        changed = true;
      }
    });
    if (changed) window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, [searchParams]);

  const rankingResource = usePublishedView(
    (id) => fetchSettlementFilterMeta("settlement", id),
    (filters, publication_id) => fetchSettlementStoreRanking({
      publication_id,
      periodType: "MONTHLY",
      periodKey: periodKey || filters.saleMonths[0] || "",
      productScope,
      productType: productType || filters.defaultProductType || "all",
      q: query || undefined,
      sortBy,
      sortOrder: "DESC",
      rankingBasis,
      page,
      pageSize: PAGE_SIZE,
    }),
    [periodKey, productScope, productType, query, rankingBasis, sortBy, page],
  );
  const metaResource = { ...rankingResource, data: rankingResource.filters };
  const meta = metaResource.data?.data;
  const activePeriodKey = periodKey || meta?.saleMonths[0] || "";
  const activeProductType = productType || meta?.defaultProductType || "all";
  const ranking = rankingResource.data?.data;
  const metaError = metaResource.rawError ? apiErrorText(metaResource.rawError, "筛选条件暂不可用，请稍后重试。") : metaResource.error;
  const rankingError = rankingResource.rawError ? apiErrorText(rankingResource.rawError, "榜单暂不可用，请稍后重试。", { 403: "当前账号没有查看该榜单的权限。", 422: "榜单筛选条件不合法，请重新选择。" }) : rankingResource.error;
  const rows = ranking?.list ?? [];
  const totals = ranking?.totals;
  const availability = ranking?.periodAvailability;
  const cumulativeUnavailable = availability?.cumulativeReady === false;
  const incompleteMonths = availability?.incompleteMonths.join("、");

  const columns: Column<SettlementStoreRankingRow>[] = [
    { key: "rank", title: "排名", align: "center", render: (row) => <span className="rank-badge">{row.rank}</span> },
    {
      key: "store",
      title: "门店",
      align: "left",
      minWidth: 180,
      render: (row) => row.storeName,
    },
    { key: "salesAmount", title: "销售金额（累计）", align: "right", render: (row) => displayMetricCurrency(row.salesAmountCumulativeCent) },
    { key: "verifiedAmount", title: "核销金额（累计）", align: "right", render: (row) => displayMetricCurrency(row.verifiedAmountCumulativeCent) },
    { key: "promotionMonth", title: "当期推广服务费", align: "right", minWidth: 150, render: (row) => displayMetricCurrency(row.promotionMonthFeeCent) },
    { key: "promotionCumulative", title: "累计推广服务费", align: "right", minWidth: 150, render: (row) => displayMetricCurrency(row.promotionCumulativeFeeCent) },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">门店结算</p>
          <h1>全国门店月度榜单</h1>
        </div>
      </section>
      <ResourceNotice analysis loading={metaResource.loading || rankingResource.loading || rankingResource.refreshing} error={metaError ?? rankingError} />
      <FilterBar>
        <SelectField disabled={!meta} label="账期" value={activePeriodKey} onChange={(value) => { setPeriodKey(value); setPage(1); }} options={(meta?.saleMonths ?? []).map((value) => ({ value, label: value }))} />
        <SelectField disabled={!meta} label="产品范围" value={productScope} onChange={(value) => { setProductScope(value); setPage(1); }} options={(meta?.productScopes ?? []).map((value) => ({ value, label: value === "all" ? "全部产品" : value }))} />
        <FilterField label="搜索门店"><FieldInput disabled={!meta} value={query} placeholder="输入门店名称" onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></FilterField>
        <SelectField label="排行依据" value={rankingBasis} onChange={(value) => {
          setRankingBasis(value as StoreFinanceRankingBasis);
          setPage(1);
        }} options={RANKING_BASIS_OPTIONS.map((option) => ({
          ...option,
          disabled: cumulativeUnavailable && option.value !== "PROMOTION_FEE_MONTH",
        }))} />
      </FilterBar>
      {availability?.monthlyReady && cumulativeUnavailable ? <ResourcePanel>本月数据已完整；累计数据{incompleteMonths ? `因 ${incompleteMonths} 尚未完成` : "尚未完成"}，暂不可用。</ResourcePanel> : null}
      {!ranking && rankingResource.loading ? <ResourcePanel>正在加载榜单…</ResourcePanel> : !ranking ? <ResourcePanel tone="error">榜单暂不可用，请稍后重试。</ResourcePanel> : (
        <>
          <section className="metric-grid store-summary-metrics">
            <MetricCard label="销售金额（累计）" value={displayMetricCurrency(totals?.salesAmountCumulativeCent)} meta={displayMetricCount(totals?.salesOrderCountCumulative, "笔销售订单")} />
            <MetricCard label="核销金额（累计）" value={displayMetricCurrency(totals?.verifiedAmountCumulativeCent)} meta={displayMetricCount(totals?.verifiedOrderCountCumulative, "笔核销订单")} />
            <MetricCard label="当期推广服务费" value={displayMetricCurrency(totals?.promotionMonthFeeCent)} meta={totals ? "当期调整后金额" : "暂无数据"} />
            <MetricCard label="累计推广服务费" value={displayMetricCurrency(totals?.promotionCumulativeFeeCent)} meta={totals ? "正式账期累计" : "暂无数据"} />
          </section>
          <section className="content-section">
            <div className="section-title">
              <div><h2>门店排名</h2><p>{ranking.scopeMode === "GLOBAL_TOP_20_EXCEPTION" ? "全国前 20 展示例外；明细仍按门店权限控制" : `共 ${ranking.total} 家门店`}</p></div>
            </div>
            {rows.length ? <DataTable columns={columns} rows={rows} rowHref={ranking.scopeMode === "AUTHORIZED" ? (row) => `/settlement?storeId=${encodeURIComponent(row.storeId)}&month=${activePeriodKey}&productScope=${encodeURIComponent(productScope)}&productType=${encodeURIComponent(activeProductType)}` : undefined} /> : <ResourcePanel>当前筛选下没有门店结果。</ResourcePanel>}
            {ranking.scopeMode === "AUTHORIZED" ? <TablePagination page={ranking.page} pageSize={ranking.pageSize} total={ranking.total} totalPages={Math.max(1, Math.ceil(ranking.total / ranking.pageSize))} rowsOnPage={rows.length} loading={rankingResource.loading} onPageChange={setPage} /> : null}
          </section>
        </>
      )}
    </div>
  );
}
