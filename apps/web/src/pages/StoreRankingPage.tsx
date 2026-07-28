import { useMemo, useState } from "react";
import {
  fetchSettlementFilterMeta,
  fetchSettlementStoreRanking,
} from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { SelectField } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type {
  PeriodType,
  RankingSortBy,
  SettlementStoreRankingRow,
  SortOrder,
} from "../types/dashboard";
import { formatCurrency, formatInteger } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";

interface StoreRankingPageProps {
  searchParams: URLSearchParams;
}

const PAGE_SIZE = 20;

export function StoreRankingPage({ searchParams }: StoreRankingPageProps) {
  const [periodType, setPeriodType] = useState<PeriodType>(
    searchParams.get("periodType") === "CUMULATIVE" ? "CUMULATIVE" : "MONTHLY",
  );
  const [periodKey, setPeriodKey] = useState(searchParams.get("periodKey") ?? "");
  const [productScope, setProductScope] = useState(
    searchParams.get("productScope") ?? "all",
  );
  const [productType, setProductType] = useState(
    searchParams.get("productType") ?? "",
  );
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [sortBy, setSortBy] = useState<RankingSortBy>("NET_SETTLEMENT_REFERENCE");
  const [sortOrder, setSortOrder] = useState<SortOrder>("DESC");
  const [page, setPage] = useState(1);

  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const meta = metaResource.data?.data;
  const activePeriodKey = periodKey || meta?.saleMonths[0] || "";
  const activeProductType = productType || meta?.defaultProductType || "all";
  const productTypes = useMemo(() => {
    const scoped = meta?.productScopeTypeMap[productScope];
    return ["all", ...(scoped ?? meta?.productTypes ?? []).filter((item) => item !== "all")];
  }, [meta, productScope]);
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
        page,
        pageSize: PAGE_SIZE,
      }),
    [periodType, activePeriodKey, productScope, activeProductType, query, sortBy, sortOrder, page],
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
    { key: "sales", title: "销售订单", align: "right", render: (row) => formatInteger(row.salesOrderCount) },
    { key: "salesAmount", title: "销售金额", align: "right", render: (row) => formatCurrency(row.salesAmountCent) },
    { key: "verified", title: "核销订单", align: "right", render: (row) => formatInteger(row.verifiedOrderCount) },
    { key: "verifiedAmount", title: "核销金额", align: "right", render: (row) => formatCurrency(row.verifiedAmountCent) },
    { key: "promotion", title: "推广服务费净额", align: "right", minWidth: 150, render: (row) => formatCurrency(row.promotionNetFeeCent) },
    { key: "management", title: "管理服务费净额", align: "right", minWidth: 150, render: (row) => formatCurrency(row.managementNetFeeCent) },
    { key: "net", title: "结算参考净额", align: "right", minWidth: 140, render: (row) => formatCurrency(row.netSettlementReferenceCent) },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">门店结算</p>
          <h1>{periodType === "CUMULATIVE" ? "全国门店累计榜单" : "全国门店月度榜单"}</h1>
          <p>排名、摘要和费用净额均来自同一服务端筛选集合。</p>
        </div>
      </section>
      <ResourceNotice loading={metaResource.loading || rankingResource.loading} error={metaError ?? rankingError} />
      <FilterBar>
        <SelectField label="统计方式" value={periodType} onChange={(value) => { setPeriodType(value as PeriodType); setPage(1); }} options={[{ value: "MONTHLY", label: "月度" }, { value: "CUMULATIVE", label: "正式累计" }]} />
        <SelectField disabled={!meta} label="账期" value={activePeriodKey} onChange={(value) => { setPeriodKey(value); setPage(1); }} options={(meta?.saleMonths ?? []).map((value) => ({ value, label: value }))} />
        <SelectField disabled={!meta} label="产品范围" value={productScope} onChange={(value) => { setProductScope(value); setProductType("all"); setPage(1); }} options={(meta?.productScopes ?? []).map((value) => ({ value, label: value === "all" ? "全部产品" : value }))} />
        <SelectField disabled={!meta} label="商品类型" value={activeProductType} onChange={(value) => { setProductType(value); setPage(1); }} options={productTypes.map((value) => ({ value, label: value === "all" ? "全部类型" : value }))} />
        <FilterField label="搜索门店"><input disabled={!meta} value={query} placeholder="输入门店名称" onChange={(event) => { setQuery(event.target.value); setPage(1); }} /></FilterField>
        <SelectField label="排序指标" value={sortBy} onChange={(value) => { setSortBy(value as RankingSortBy); setPage(1); }} options={[{ value: "NET_SETTLEMENT_REFERENCE", label: "结算参考净额" }, { value: "PROMOTION_FEE", label: "推广服务费" }, { value: "MANAGEMENT_FEE", label: "管理服务费" }, { value: "SALES_AMOUNT", label: "销售金额" }, { value: "VERIFIED_AMOUNT", label: "核销金额" }]} />
        <SelectField label="排序方向" value={sortOrder} onChange={(value) => { setSortOrder(value as SortOrder); setPage(1); }} options={[{ value: "DESC", label: "从高到低" }, { value: "ASC", label: "从低到高" }]} />
      </FilterBar>
      {periodType === "CUMULATIVE" && activePeriodKey < (meta?.formalPeriodStartMonth ?? "2026-08") ? <ResourcePanel>累计排名从 {meta?.formalPeriodStartMonth ?? "2026-08"} 正式账期开始，当前账期不计入正式累计。</ResourcePanel> : null}
      {!ranking && rankingResource.loading ? <ResourcePanel>正在加载榜单…</ResourcePanel> : !ranking ? <ResourcePanel tone="error">榜单暂不可用，请稍后重试。</ResourcePanel> : (
        <>
          <section className="metric-grid metric-grid--three">
            <MetricCard label="销售金额" value={formatCurrency(totals?.salesAmountCent ?? 0)} meta={`${formatInteger(totals?.salesOrderCount ?? 0)} 笔销售订单`} />
            <MetricCard label="核销金额" value={formatCurrency(totals?.verifiedAmountCent ?? 0)} meta={`${formatInteger(totals?.verifiedOrderCount ?? 0)} 笔核销订单`} />
            <MetricCard label="推广服务费净额" value={formatCurrency(totals?.promotionNetFeeCent ?? 0)} meta="调整后净额" />
            <MetricCard label="管理服务费净额" value={formatCurrency(totals?.managementNetFeeCent ?? 0)} meta="调整后净额" />
            <MetricCard label="结算参考净额" value={formatCurrency(totals?.netSettlementReferenceCent ?? 0)} meta="推广费减管理费" />
          </section>
          <section className="content-section">
            <div className="section-title"><div><h2>门店排名</h2><p>{ranking.scopeMode === "GLOBAL_TOP_20_EXCEPTION" ? "全国前 20 展示例外；明细仍按门店权限控制" : `共 ${ranking.total} 家门店`}</p></div></div>
            {rows.length ? <DataTable columns={columns} rows={rows} rowHref={ranking.scopeMode === "AUTHORIZED" ? (row) => `/settlement?storeId=${encodeURIComponent(row.storeId)}&month=${activePeriodKey}&productScope=${encodeURIComponent(productScope)}&productType=${encodeURIComponent(activeProductType)}` : undefined} /> : <ResourcePanel>当前筛选下没有门店结果。</ResourcePanel>}
            {ranking.scopeMode === "AUTHORIZED" ? <TablePagination page={ranking.page} pageSize={ranking.pageSize} total={ranking.total} totalPages={Math.max(1, Math.ceil(ranking.total / ranking.pageSize))} rowsOnPage={rows.length} loading={rankingResource.loading} onPageChange={setPage} /> : null}
          </section>
        </>
      )}
    </div>
  );
}
