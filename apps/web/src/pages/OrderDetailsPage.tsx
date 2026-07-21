import { useMemo, useState } from "react";
import {
  exportOrderFeeDetails,
  fetchOrderFeeDetails,
  fetchSettlementFilterMeta,
  type OrderFeeDetailsQuery,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar, FilterField } from "../components/Filters";
import { SelectField } from "../components/FormControls";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type { FeeDirection, OrderFeeDetailRow } from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { apiErrorText } from "../utils/apiErrors";

interface OrderDetailsPageProps {
  searchParams: URLSearchParams;
}

const PAGE_SIZE = 50;

function errorText(error: unknown): string {
  return apiErrorText(error, "明细服务暂不可用，请稍后重试。", {
    403: "当前账号没有查看或导出该门店明细的权限。",
    409: "当前筛选没有可导出的记录。",
    422: "来源上下文已变化，请返回单店分账重新进入。",
  });
}

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "有效",
  ADJUSTED: "有调整",
  AVAILABLE: "可使用",
  BLOCKED: "数据阻断",
  CANCELED: "已取消",
  CANCELLED: "已取消",
  CLOSED: "已关闭",
  CONFIRMED: "已确认",
  DATA_QUALITY_BLOCKED: "数据质量阻断",
  FULFILLED: "已核销",
  LOCKED: "已锁账",
  PAID: "已支付",
  PENDING_CONFIRMATION: "待确认",
  REFUNDED: "已退款",
  SUPERSEDED: "已被新版本替代",
  UNKNOWN: "未知状态",
  UNPAID_CLOSED: "已关闭",
  VALID: "有效",
  VERIFIED: "已核销",
};

function statusLabel(value?: string | null): string {
  const normalized = value?.trim().toUpperCase();
  return normalized ? STATUS_LABELS[normalized] ?? "未知状态" : "未知状态";
}

function percent(rate: string): string {
  return `${(Number(rate) * 100).toFixed(2).replace(/\.00$/, "")}%`;
}

function navigate(href: string) {
  window.history.pushState(null, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

export function OrderDetailsPage({ searchParams }: OrderDetailsPageProps) {
  const [feeDirection, setFeeDirection] = useState<FeeDirection>(
    searchParams.get("feeDirection") === "MANAGEMENT" ? "MANAGEMENT" : "PROMOTION",
  );
  const [saleMonth, setSaleMonth] = useState(searchParams.get("saleMonth") ?? "");
  const [verifyMonth, setVerifyMonth] = useState(searchParams.get("verifyMonth") ?? "");
  const [dataStatus, setDataStatus] = useState(searchParams.get("dataStatus") ?? "");
  const [queryText, setQueryText] = useState(searchParams.get("q") ?? "");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const metaResource = useApiResource(fetchSettlementFilterMeta, []);
  const meta = metaResource.data?.data;

  const statementId = searchParams.get("statementId") ?? undefined;
  const statementLineId = searchParams.get("statementLineId") ?? undefined;
  const storeId = searchParams.get("storeId") ?? searchParams.get("store_id") ?? undefined;
  const month = searchParams.get("month") ?? undefined;
  const feeRates = searchParams.getAll("feeRates");
  const ruleVersions = searchParams.getAll("ruleVersions");
  const productScope = searchParams.get("productScope") ?? searchParams.get("product_scope") ?? "all";
  const productType = searchParams.get("productType") ?? searchParams.get("product_type") ?? meta?.defaultProductType ?? "all";
  const hasStatementSource = Boolean(statementId && statementLineId);
  const hasPreviewSource = Boolean(storeId && month);
  const hasSourceContext = hasStatementSource || hasPreviewSource;
  const directionIsFrozen = Boolean(statementLineId || feeRates.length || ruleVersions.length);

  const requestQuery = useMemo<OrderFeeDetailsQuery>(() => ({
    statementId: hasStatementSource ? statementId : undefined,
    statementLineId: hasStatementSource ? statementLineId : undefined,
    storeId: hasPreviewSource && !hasStatementSource ? storeId : undefined,
    month: hasPreviewSource && !hasStatementSource ? month : undefined,
    saleMonth: saleMonth || undefined,
    verifyMonth: verifyMonth || undefined,
    feeDirection,
    productScope,
    productType,
    feeRates,
    ruleVersions,
    dataStatus: dataStatus || undefined,
    q: queryText || undefined,
    page,
    pageSize: PAGE_SIZE,
  }), [hasStatementSource, hasPreviewSource, statementId, statementLineId, storeId, month, saleMonth, verifyMonth, feeDirection, productScope, productType, feeRates.join("|"), ruleVersions.join("|"), dataStatus, queryText, page]);
  const detailsResource = useApiResource(
    () => fetchOrderFeeDetails(requestQuery),
    [requestQuery],
    { enabled: hasSourceContext },
  );
  const details = detailsResource.data?.data;
  const rows = details?.list ?? [];
  const detailsError = detailsResource.rawError ?? detailsResource.error;
  const metaError = metaResource.rawError ? apiErrorText(metaResource.rawError, "筛选条件暂不可用，请稍后重试。") : metaResource.error;
  const normalizedContext = details?.context;
  const displayedDirection = normalizedContext?.feeDirection ?? feeDirection;
  const returnStoreId = normalizedContext?.storeId ?? storeId;
  const returnMonth = normalizedContext?.month ?? month;
  const returnSearch = new URLSearchParams();
  if (returnStoreId) returnSearch.set("storeId", returnStoreId);
  if (returnMonth) returnSearch.set("month", returnMonth);
  if (normalizedContext?.productScope ?? productScope) returnSearch.set("productScope", normalizedContext?.productScope ?? productScope);
  if (normalizedContext?.productType ?? productType) returnSearch.set("productType", normalizedContext?.productType ?? productType);
  const returnHref = `/settlement${returnSearch.size ? `?${returnSearch.toString()}` : ""}`;

  const handleExportOrders = async () => {
    if (!details) return;
    setExporting(true);
    setExportError(null);
    const context = details.context;
    try {
      await exportOrderFeeDetails({
        ...requestQuery,
        statementId: context.statementId ?? undefined,
        statementLineId: context.statementLineId ?? undefined,
        storeId: context.statementId ? undefined : context.storeId ?? undefined,
        month: context.statementId ? undefined : context.month ?? undefined,
        feeDirection: context.feeDirection,
        productScope: context.productScope,
        productType: context.productType,
        feeRates: context.feeRates,
        ruleVersions: context.ruleVersions,
      });
    } catch (error) {
      setExportError(errorText(error));
    } finally {
      setExporting(false);
    }
  };

  const columns: Column<OrderFeeDetailRow>[] = [
    {
      key: "order",
      title: "订单 / 券 / 状态",
      align: "left",
      sticky: true,
      minWidth: 210,
      render: (row) => <span className="identifier-stack"><strong>{row.orderId}</strong><small>{row.couponId}</small><small>{statusLabel(row.orderStatus)} / {statusLabel(row.couponStatus)}</small></span>,
    },
    {
      key: "product",
      title: "商品 / 渠道",
      align: "left",
      minWidth: 220,
      render: (row) => <span className="identifier-stack"><strong>{row.productName || row.skuName || "未匹配商品"}</strong><small>{row.skuId}</small><small>{row.productScope} / {row.productType} · {row.saleChannel || "-"}</small></span>,
    },
    {
      key: "stores",
      title: "销售门店 → 核销门店",
      align: "left",
      minWidth: 250,
      render: (row) => <span className="identifier-stack"><strong>{row.saleStoreName || "-"} → {row.verifyStoreName || "-"}</strong><small>销售 {formatDateTime(row.saleTime)} · 核销 {formatDateTime(row.verifyTime)}</small><small>匹配日 {row.ruleMatchDate || "-"}</small></span>,
    },
    { key: "months", title: "原始 / 销售 / 核销月", minWidth: 190, render: (row) => `${row.originalBusinessMonth} / ${row.saleMonth || "-"} / ${row.verifyMonth || "-"}` },
    { key: "source", title: "来源金额 / 退款", align: "right", minWidth: 160, render: (row) => <span className="identifier-stack"><strong>{formatCurrency(row.sourceAmountCent)}</strong><small>退款 {formatCurrency(row.refundedAmountCent)}</small></span> },
    { key: "bases", title: "原始 / 调整 / 净基数", align: "right", minWidth: 190, render: (row) => `${formatCurrency(row.originalBaseCent)} / ${formatCurrency(row.adjustmentBaseCent)} / ${formatCurrency(row.adjustedNetBaseCent)}` },
    { key: "rate", title: "实际费率", align: "right", render: (row) => percent(row.feeRate) },
    { key: "fees", title: "原始 / 调整 / 净费用", align: "right", minWidth: 190, render: (row) => `${formatCurrency(row.originalFeeCent)} / ${formatCurrency(row.adjustmentFeeCent)} / ${formatCurrency(row.adjustedNetFeeCent)}` },
    {
      key: "status",
      title: "结果 / 数据状态",
      minWidth: 180,
      render: (row) => <span className="identifier-stack"><strong>{statusLabel(row.resultStatus)} / {statusLabel(row.dataStatus)}</strong><small>{row.ruleVersion}</small><small>{row.statementId ? `账单 ${row.statementId}` : "未关联账单"}{row.statementLineId ? ` · 行 ${row.statementLineId}` : ""}{row.statementStatus ? ` · ${statusLabel(row.statementStatus)}` : ""}</small></span>,
    },
    {
      key: "adjustments",
      title: "后续调整",
      minWidth: 280,
      render: (row) => row.adjustments.length ? <details><summary>{row.adjustments.length} 条调整</summary>{row.adjustments.map((item) => <p key={item.adjustmentId}>{item.adjustmentPostingMonth} · {item.adjustmentType} · 基数 {formatCurrency(item.adjustmentBaseCent)} · 费用 {formatCurrency(item.adjustmentFeeCent)} · {item.ruleVersion} · {item.adjustmentReason || "-"} · {formatDateTime(item.occurredAt)}</p>)}</details> : "无后续调整",
    },
  ];

  const setDirection = (next: FeeDirection) => {
    if (directionIsFrozen && next !== feeDirection) return;
    setFeeDirection(next);
    setPage(1);
  };

  return (
    <div className="page-stack page-stack--data-workspace">
      <section className="page-heading"><div><p className="eyebrow">门店结算</p><h1>{displayedDirection === "PROMOTION" ? "推广费订单明细" : "管理服务费订单明细"}</h1><p>{normalizedContext?.statementId || hasStatementSource ? "账单行冻结来源" : normalizedContext?.month || hasPreviewSource ? `${normalizedContext?.month ?? month} 预览来源` : "请从单店分账的费用汇总行进入"} · 费用不在前端重算</p></div></section>
      <ResourceNotice loading={metaResource.loading || detailsResource.loading} error={metaError ?? (detailsError ? errorText(detailsError) : undefined)} />
      <div className="fee-direction-tabs" role="group" aria-label="费用类型">
        <Button type="button" aria-pressed={displayedDirection === "PROMOTION"} disabled={directionIsFrozen && displayedDirection !== "PROMOTION"} onClick={() => setDirection("PROMOTION")}>推广服务费</Button>
        <Button type="button" aria-pressed={displayedDirection === "MANAGEMENT"} disabled={directionIsFrozen && displayedDirection !== "MANAGEMENT"} onClick={() => setDirection("MANAGEMENT")}>管理服务费</Button>
      </div>
      {directionIsFrozen ? <p className="muted-copy">当前明细绑定了具体费用行、费率和规则版本；如需查看另一费用类型，请返回单店分账选择对应汇总行。</p> : null}
      <FilterBar className="filter-bar--compact detail-filter-bar detail-filter-bar--single-line">
        <SelectField label="销售月份" value={saleMonth} onChange={(value) => { setSaleMonth(value); setPage(1); }} options={[{ value: "", label: "全部" }, ...(meta?.saleMonths ?? []).map((value) => ({ value, label: value }))]} />
        <SelectField label="核销月份" value={verifyMonth} onChange={(value) => { setVerifyMonth(value); setPage(1); }} options={[{ value: "", label: "全部" }, ...(meta?.verifyMonths ?? []).map((value) => ({ value, label: value }))]} />
        <SelectField label="数据状态" value={dataStatus} onChange={(value) => { setDataStatus(value); setPage(1); }} options={[{ value: "", label: "全部" }, { value: "VALID", label: "有效" }, { value: "ADJUSTED", label: "有调整" }, { value: "BLOCKED", label: "数据阻断" }, { value: "LOCKED", label: "已锁账" }]} />
        <FilterField label="搜索"><input value={queryText} placeholder="订单、券码、SKU 或商品" onChange={(event) => { setQueryText(event.target.value); setPage(1); }} /></FilterField>
      </FilterBar>
      <section className="content-section content-section--data-workspace">
        <div className="section-title"><div><h2>明细记录</h2><p>{details ? `${details.total} 条 · ${details.context.feeRates.length} 种费率 · ${details.context.ruleVersions.length} 个版本` : hasSourceContext ? "正在读取来源上下文" : "缺少有效的来源上下文"}</p></div><div className="section-title-actions"><Button type="button" icon="fileDownload" size="sm" loading={exporting} disabled={exporting || !details?.total} onClick={handleExportOrders}>{exporting ? "导出中" : "导出"}</Button></div></div>
        {exportError ? <p className="export-error" role="status">{exportError}</p> : null}
        {!hasSourceContext ? <ResourcePanel>请从单店分账中的推广服务费或管理服务费汇总行进入。<br /><Button type="button" variant="text" onClick={() => navigate(returnHref)}>返回单店分账</Button></ResourcePanel> : !details && detailsResource.loading ? <ResourcePanel>正在加载订单费用明细…</ResourcePanel> : !details ? <ResourcePanel tone="error">{errorText(detailsError)}<br /><Button type="button" variant="text" onClick={() => navigate(returnHref)}>返回单店分账</Button></ResourcePanel> : rows.length ? <><DataTable columns={columns} rows={rows} stickyHeader="container" tableClassName="data-table--details" /><TablePagination page={details.page} pageSize={details.pageSize} total={details.total} totalPages={Math.max(1, Math.ceil(details.total / details.pageSize))} rowsOnPage={rows.length} loading={detailsResource.loading} onPageChange={setPage} /></> : <ResourcePanel>当前筛选下没有费用记录。</ResourcePanel>}
      </section>
    </div>
  );
}
