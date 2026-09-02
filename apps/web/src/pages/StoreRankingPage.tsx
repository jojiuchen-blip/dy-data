import { useState } from "react";
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
import { useApiResource } from "../hooks/useApiResource";
import type {
  PeriodType,
  RankingSortBy,
  SettlementStoreRankingRow,
  SortOrder,
  StoreFinanceRankingBasis,
} from "../types/dashboard";
import { formatCurrency, formatInteger } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";

interface StoreRankingPageProps {
  searchParams: URLSearchParams;
}

const PAGE_SIZE = 20;
const displayMetricCurrency = (value: number | undefined) =>
  value === undefined ? "暂无数据" : formatCurrency(value);
const displayMetricCount = (value: number | undefined, unit: string) =>
  value === undefined ? "暂无数据" : `${formatInteger(value)} ${unit}`;

type RankingBasis = StoreFinanceRankingBasis;

const RANKING_BASIS_OPTIONS: Array<{ value: RankingBasis; label: string }> = [
  { value: "SALES_AMOUNT_CUMULATIVE", label: "销售金额（累计）" },
  { value: "VERIFIED_AMOUNT_CUMULATIVE", label: "核销金额（累计）" },
  { value: "PROMOTION_FEE_MONTH", label: "当期推广服务费" },
  { value: "PROMOTION_FEE_CUMULATIVE", label: "累计推广服务费" },
];

function rankingBasisFromQuery(value: string | null): RankingBasis {
  return RANKING_BASIS_OPTIONS.some((option) => option.value === value)
    ? value as RankingBasis
    : "PROMOTION_FEE_MONTH";
}

function rankingSortByForBasis(basis: RankingBasis): RankingSortBy {
  switch (basis) {
    case "SALES_AMOUNT_CUMULATIVE":
      return "SALES_AMOUNT";
    case "VERIFIED_AMOUNT_CUMULATIVE":
      return "VERIFIED_AMOUNT";
    case "PROMOTION_FEE_CUMULATIVE":
    case "PROMOTION_FEE_MONTH":
    default:
      return "PROMOTION_FEE";
  }
}

function periodTypeForRankingBasis(basis: RankingBasis): PeriodType {
  return basis === "PROMOTION_FEE_MONTH" ? "MONTHLY" : "CUMULATIVE";
}

export function StoreRankingPage({ searchParams }: StoreRankingPageProps) {
  const initialRankingBasis = rankingBasisFromQuery(
    searchParams.get("rankingBasis"),
  );
  const [periodType, setPeriodType] = useState<PeriodType>(
    periodTypeForRankingBasis(initialRankingBasis),
  );
  const [periodKey, setPeriodKey] = useState(searchParams.get("periodKey") ?? "");
  const [productScope, setProductScope] = useState(
    searchParams.get("productScope") ?? "all",
  );
  const productType = searchParams.get("productType") ?? "";
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [rankingBasis, setRankingBasis] = useState<RankingBasis>(
    initialRankingBasis,
  );
  const [page, setPage] = useState(1);

  const sortBy = rankingSortByForBasis(rankingBasis);
  const sortOrder: SortOrder = "DESC";

  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const meta = metaResource.data?.data;
  const activePeriodKey = periodKey || meta?.saleMonths[0] || "";
  const activeProductType = productType || meta?.defaultProductType || "all";
  const rankingResource = useApiResource(
    () =>
      fetchSettlementStoreRanking({
        periodType,
        periodKey: activePeriodKey,
        productScope,
        productType: activeProductType,
        q: query || undefined,
        sortBy,
        sortOrder,
        rankingBasis,
        page,
        pageSize: PAGE_SIZE,
      }),
    [periodType, activePeriodKey, productScope, activeProductType, query, sortBy, rankingBasis, page],
    { enabled: Boolean(meta && activePeriodKey) },
  );
  const ranking = rankingResource.data?.data;
  const metaError = metaResource.rawError ? apiErrorText(metaResource.rawError, "筛选条件暂不可用，请稍后重试。") : metaResource.error;
  const rankingError = rankingResource.rawError ? apiErrorText(rankingResource.rawError, "榜单暂不可用，请稍后重试。", { 403: "当前账号没有查看该榜单的权限。", 422: "榜单筛选条件不合法，请重新选择。" }) : rankingResource.error;
  const rows = ranking?.list ?? [];
  const totals = ranking?.totals;

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
      <ResourceNotice loading={metaResource.loading || rankingResource.loading} error={metaError ?? rankingError} />
      <FilterBar>
        <SelectField label="统计方式" value={periodType} onChange={(value) => {
          const nextPeriodType = value as PeriodType;
          setPeriodType(nextPeriodType);
          setRankingBasis((current) => nextPeriodType === "MONTHLY"
            ? "PROMOTION_FEE_MONTH"
            : current === "PROMOTION_FEE_MONTH"
              ? "PROMOTION_FEE_CUMULATIVE"
              : current);
          setPage(1);
        }} options={[{ value: "MONTHLY", label: "月度" }, { value: "CUMULATIVE", label: "正式累计" }]} />
        <SelectField disabled={!meta} label="账期" value={activePeriodKey} onChange={(value) => { setPeriodKey(value); setPage(1); }} options={(meta?.saleMonths ?? []).map((value) => ({ value, label: value }))} />
        <SelectField disabled={!meta} label="产品范围" value={productScope} onChange={(value) => { setProductScope(value); setPage(1); }} options={(meta?.productScopes ?? []).map((value) => ({ value, label: value === "all" ? "全部产品" : value }))} />
        <FilterField label="搜索门店"><FieldInput disabled={!meta} value={query} placeholder="输入门店名称" onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></FilterField>
      </FilterBar>
      {periodType === "CUMULATIVE" && activePeriodKey < (meta?.formalPeriodStartMonth ?? "2026-08") ? <ResourcePanel>累计排名从 {meta?.formalPeriodStartMonth ?? "2026-08"} 正式账期开始，当前账期不计入正式累计。</ResourcePanel> : null}
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
              <SelectField label="排行依据" value={rankingBasis} onChange={(value) => {
                const nextBasis = value as RankingBasis;
                setRankingBasis(nextBasis);
                setPeriodType(periodTypeForRankingBasis(nextBasis));
                setPage(1);
              }} options={RANKING_BASIS_OPTIONS} />
            </div>
            {rows.length ? <DataTable columns={columns} rows={rows} rowHref={ranking.scopeMode === "AUTHORIZED" ? (row) => `/settlement?storeId=${encodeURIComponent(row.storeId)}&month=${activePeriodKey}&productScope=${encodeURIComponent(productScope)}&productType=${encodeURIComponent(activeProductType)}` : undefined} /> : <ResourcePanel>当前筛选下没有门店结果。</ResourcePanel>}
            {ranking.scopeMode === "AUTHORIZED" ? <TablePagination page={ranking.page} pageSize={ranking.pageSize} total={ranking.total} totalPages={Math.max(1, Math.ceil(ranking.total / ranking.pageSize))} rowsOnPage={rows.length} loading={rankingResource.loading} onPageChange={setPage} /> : null}
          </section>
        </>
      )}
    </div>
  );
}
