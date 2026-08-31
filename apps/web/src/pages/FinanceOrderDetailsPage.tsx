import { FormEvent, useState } from "react";
import { downloadFinanceOrderDetails, fetchFinanceOrderDetails } from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput, SelectField, TextField } from "../components/FormControls";
import { ResourceNotice } from "../components/ResourceState";
import { TertiaryNav } from "../components/TertiaryNav";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type {
  FeeDirection,
  FinanceOrderDetailRow,
  FinanceOrderDetailsQuery,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import {
  displayFeeDirection,
  displayFinanceAdjustmentType,
  displayFinanceInvoiceStatus,
  displayFinanceOrderRowType,
  displayFinanceOrderStatus,
  displayFinanceSaleChannel,
  displayFinanceSettlementStatus,
} from "../utils/userFacingLabels";

interface FinanceOrderDetailsPageProps {
  feeDirection: FeeDirection;
  searchParams: URLSearchParams;
}

type FilterDraft = {
  q: string;
  month: string;
  saleChannel: string;
  invoiceStatus: string;
  settlementStatus: string;
  submittedFrom: string;
  submittedTo: string;
  verifyFrom: string;
  verifyTo: string;
  pageSize: number;
};

function defaultStatementMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function optional(value: string): string | undefined {
  const normalized = value.trim();
  return normalized || undefined;
}

function displayOrderInvoiceStatus(
  value: string | null,
  feeDirection: FeeDirection,
): string {
  if (feeDirection === "MANAGEMENT") {
    if (value === "APPROVED_SETTLED") return "已开票";
    if (value === "PENDING_INVOICE") return "待开票";
  }
  return displayFinanceInvoiceStatus(value);
}

function optionalDate(value: string, endOfDay = false): string | undefined {
  if (!value) return undefined;
  return new Date(`${value}${endOfDay ? "T23:59:59.999" : "T00:00:00.000"}`).toISOString();
}

function legacySearchFromParams(searchParams: URLSearchParams): string {
  return ["storeId", "storeName", "sapCode", "invoiceNumber", "orderId", "skuId"]
    .map((key) => searchParams.get(key) ?? "")
    .filter(Boolean)
    .join(" ");
}

function initialDraft(searchParams: URLSearchParams): FilterDraft {
  return {
    q: searchParams.get("q") ?? legacySearchFromParams(searchParams),
    month: searchParams.get("month") ?? defaultStatementMonth(),
    saleChannel: searchParams.get("saleChannel") ?? "",
    invoiceStatus: searchParams.get("invoiceStatus") ?? "",
    settlementStatus: searchParams.get("settlementStatus") ?? "",
    submittedFrom: searchParams.get("submittedFrom")?.slice(0, 10) ?? "",
    submittedTo: searchParams.get("submittedTo")?.slice(0, 10) ?? "",
    verifyFrom: searchParams.get("verifyFrom")?.slice(0, 10) ?? "",
    verifyTo: searchParams.get("verifyTo")?.slice(0, 10) ?? "",
    pageSize: Number(searchParams.get("pageSize")) || 50,
  };
}

function makeQuery(
  feeDirection: FeeDirection,
  draft: FilterDraft,
  page: number,
): FinanceOrderDetailsQuery {
  return {
    month: draft.month,
    feeDirection,
    q: optional(draft.q),
    saleChannel: optional(draft.saleChannel),
    invoiceStatus: optional(draft.invoiceStatus),
    settlementStatus: optional(draft.settlementStatus),
    submittedFrom: optionalDate(draft.submittedFrom),
    submittedTo: optionalDate(draft.submittedTo, true),
    verifyFrom: optionalDate(draft.verifyFrom),
    verifyTo: optionalDate(draft.verifyTo, true),
    page,
    pageSize: draft.pageSize,
  };
}

function FinanceOrderDetail({ row }: { row: FinanceOrderDetailRow }) {
  const money = (value: number | null) => value == null ? "—" : formatCurrency(value);
  const values = [
    ["分录 ID", row.statementEntryId],
    ["账单 ID", row.statementId],
    ["门店 ID", row.storeId],
    ["门店名称", row.storeName],
    ["SAP", row.sapCode],
    ["账单归属门店 ID", row.billingStoreId],
    ["账单归属门店", row.billingStoreName],
    ["服务店名称", row.serviceStoreName],
    ["有效 SAP", row.effectiveSapCode],
    ["账期", row.statementMonth],
    ["费用方向", displayFeeDirection(row.feeDirection)],
    ["订单 ID", row.orderId],
    ["券 ID", row.couponId],
    ["订单状态", displayFinanceOrderStatus(row.orderStatus)],
    ["券状态", displayFinanceOrderStatus(row.couponStatus)],
    ["商品名称", row.productName],
    ["SKU ID", row.skuId],
    ["SKU 名称", row.skuName],
    ["商品类型", row.productType],
    ["销售渠道", displayFinanceSaleChannel(row.saleChannel)],
    ["销售门店 ID", row.saleStoreId],
    ["销售门店", row.saleStoreName],
    ["核销门店 ID", row.verifyStoreId],
    ["核销门店", row.verifyStoreName],
    ["销售时间", formatDateTime(row.saleTime)],
    ["核销时间", formatDateTime(row.verifyTime)],
    ["实收金额", money(row.receivedAmountCent)],
    ["冻结计费基数", money(row.frozenFeeBaseCent)],
    ["实际费率", row.actualFeeRate],
    ["冻结费用金额", money(row.frozenFeeAmountCent)],
    ["退款/调整时间", formatDateTime(row.refundTime)],
    ["调整类型", displayFinanceAdjustmentType(row.adjustmentType)],
    ["行类型", displayFinanceOrderRowType(row.rowType)],
    ["发票号码", row.invoiceNumber],
    ["提交时间", formatDateTime(row.submittedAt)],
    ["发票状态", displayOrderInvoiceStatus(row.invoiceStatus, row.feeDirection)],
    ["结算时间", formatDateTime(row.settledAt)],
    ["不通过原因", row.rejectionReason],
    ["导入时间", formatDateTime(row.importedAt)],
    ["结算状态", displayFinanceSettlementStatus(row.settlementStatus)],
    ["厂家扣款日期", row.factoryDeductionDate],
    ["厂家扣款金额", money(row.factoryDeductionAmountCent)],
  ];
  return (
    <dl className="finance-order-detail-grid">
      {values.map(([label, value]) => (
        <div key={String(label)}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>
      ))}
    </dl>
  );
}

function storeCell(name: string | null, id: string | null) {
  return <span><strong>{name ?? "—"}</strong><br /><small>{id ?? "—"}</small></span>;
}

export function FinanceOrderDetailsPage({ feeDirection, searchParams }: FinanceOrderDetailsPageProps) {
  const [draft, setDraft] = useState<FilterDraft>(() => initialDraft(searchParams));
  const [query, setQuery] = useState<FinanceOrderDetailsQuery>(() => makeQuery(feeDirection, initialDraft(searchParams), 1));
  const [selectedRow, setSelectedRow] = useState<FinanceOrderDetailRow | null>(null);
  const [exportState, setExportState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [exportMessage, setExportMessage] = useState("");
  const queryKey = JSON.stringify(query);
  const resource = useApiResource(() => fetchFinanceOrderDetails(query), [queryKey]);
  const resourceBusy = resource.loading || resource.refreshing;
  const rows = resource.data?.data.list ?? [];
  const total = resource.data?.data.total ?? 0;
  const page = resource.data?.data.page ?? query.page ?? 1;
  const pageSize = resource.data?.data.pageSize ?? query.pageSize ?? 50;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const invoiceStatusOptions = feeDirection === "PROMOTION"
    ? [
        { value: "", label: "全部状态" },
        { value: "PENDING_INVOICE", label: "待开票" },
        { value: "SUBMITTED_PENDING_FACTORY_REVIEW", label: "提交成功，待厂端审核" },
        { value: "APPROVED_SETTLED", label: "审核通过，已结算" },
        { value: "REJECTED_REUPLOAD", label: "审核不通过" },
      ]
    : [
        { value: "", label: "全部状态" },
        { value: "PENDING_INVOICE", label: "待开票" },
        { value: "APPROVED_SETTLED", label: "已开票" },
      ];

  const columns: Column<FinanceOrderDetailRow>[] = [
    { key: "month", title: "账期", sticky: true, width: 100, render: (row) => row.statementMonth },
    { key: "billingStore", title: "账单归属门店", minWidth: 210, render: (row) => storeCell(row.billingStoreName, row.billingStoreId) },
    { key: "serviceStore", title: "服务店名称", minWidth: 190, render: (row) => row.serviceStoreName ?? "—" },
    { key: "sap", title: "有效 SAP", minWidth: 130, render: (row) => row.effectiveSapCode ?? "—" },
    { key: "order", title: "订单", minWidth: 190, render: (row) => row.orderId },
    { key: "coupon", title: "券", minWidth: 180, render: (row) => row.couponId ?? "—" },
    { key: "status", title: "状态", minWidth: 180, render: (row) => `${displayFinanceOrderStatus(row.orderStatus)} / ${displayFinanceOrderStatus(row.couponStatus)}` },
    { key: "product", title: "商品", minWidth: 190, render: (row) => row.productName ?? "—" },
    { key: "sku", title: "SKU ID", minWidth: 150, render: (row) => row.skuId ?? "—" },
    { key: "productType", title: "商品类型", minWidth: 140, render: (row) => row.productType ?? "—" },
    { key: "channel", title: "销售渠道", minWidth: 120, render: (row) => displayFinanceSaleChannel(row.saleChannel) },
    { key: "saleStore", title: "销售门店", minWidth: 190, render: (row) => storeCell(row.saleStoreName, row.saleStoreId) },
    { key: "verifyStore", title: "核销门店", minWidth: 190, render: (row) => storeCell(row.verifyStoreName, row.verifyStoreId) },
    { key: "saleTime", title: "销售时间", minWidth: 170, render: (row) => formatDateTime(row.saleTime) },
    { key: "verifyTime", title: "核销时间", minWidth: 170, render: (row) => formatDateTime(row.verifyTime) },
    { key: "refundTime", title: "退款时间", minWidth: 170, render: (row) => formatDateTime(row.refundTime) },
    { key: "received", title: "实收金额", minWidth: 130, align: "right", render: (row) => row.receivedAmountCent == null ? "—" : formatCurrency(row.receivedAmountCent) },
    { key: "rate", title: "实际费率", minWidth: 120, align: "right", render: (row) => row.actualFeeRate ?? "—" },
    { key: "invoiceNumber", title: "对应发票号码", minWidth: 210, render: (row) => row.invoiceNumber ?? "—" },
    { key: "submitted", title: "发票提交时间", minWidth: 170, render: (row) => formatDateTime(row.submittedAt ?? row.importedAt) },
    { key: "invoiceStatus", title: "发票审核状态", minWidth: 180, render: (row) => displayOrderInvoiceStatus(row.invoiceStatus, row.feeDirection) },
    { key: "settlementDate", title: "发票结算日期", minWidth: 160, render: (row) => row.settlementDate ?? "—" },
    { key: "rejection", title: "审核不通过原因", minWidth: 220, render: (row) => row.rejectionReason ?? "—" },
  ];

  const setField = <K extends keyof FilterDraft>(key: K, value: FilterDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const submitFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSelectedRow(null);
    setQuery(makeQuery(feeDirection, draft, 1));
  };

  const resetFilters = () => {
    const next = initialDraft(new URLSearchParams());
    setDraft(next);
    setSelectedRow(null);
    setQuery(makeQuery(feeDirection, next, 1));
  };

  const changePage = (nextPage: number) => {
    setSelectedRow(null);
    setQuery((current) => ({ ...current, page: nextPage }));
  };

  const onPageSizeChange = (nextPageSize: number) => {
    setDraft((current) => ({ ...current, pageSize: nextPageSize }));
    setSelectedRow(null);
    setQuery((current) => ({ ...current, page: 1, pageSize: nextPageSize }));
  };

  const handleExport = async () => {
    setExportState("loading");
    setExportMessage("导出中，请稍候。");
    try {
      const { page: _page, pageSize: _pageSize, ...exportQuery } = query;
      const result = await downloadFinanceOrderDetails(exportQuery);
      setExportState("success");
      setExportMessage(result.result === "EMPTY" ? "筛选结果为空，已下载仅含表头的文件。" : `导出成功：${result.fileName}`);
    } catch (error) {
      setExportState("error");
      setExportMessage(userFacingError(error, "导出失败，请缩小筛选范围后重试。"));
    }
  };

  return (
    <div className="page-stack finance-page">
      <TertiaryNav
        label="订单明细费用方向"
        items={[
          { href: "/finance/orders/promotion", label: "推广服务费明细", current: feeDirection === "PROMOTION" },
          { href: "/finance/orders/management", label: "管理服务费明细", current: feeDirection === "MANAGEMENT" },
        ]}
      />
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">财务管理员</p>
          <h1>{feeDirection === "PROMOTION" ? "推广服务费订单明细" : "管理服务费订单明细"}</h1>
          <p>原费用与退款或取消调整分别成行；列表、总数和导出统一使用正式冻结事实。</p>
        </div>
        <Button loading={exportState === "loading"} onClick={handleExport} variant="primary">{exportState === "loading" ? "导出中" : "导出全部命中结果"}</Button>
      </section>

      <div className="finance-guidance" role="note">
        <strong>导出文件包含全部底层字段。</strong>
        <span>页面表头、筛选、总数和导出使用同一服务端查询口径。</span>
      </div>

      <form className="finance-order-filters" aria-label="订单明细筛选条件" onSubmit={submitFilters}>
        <div className="finance-order-filters__row finance-order-filters__row--primary">
          <TextField fieldClassName="finance-order-filter--search" label="搜索" onChange={(event) => setField("q", event.target.value)} placeholder="搜索门店、SAP、发票号码、订单 ID 或 SKU ID" type="search" value={draft.q} />
          <TextField label="筛选账期" onChange={(event) => setField("month", event.target.value)} type="month" value={draft.month} />
          <SelectField label="销售渠道" onChange={(value) => setField("saleChannel", value)} options={[{ value: "", label: "全部渠道" }, { value: "LIVE", label: "直播" }, { value: "SHORT_VIDEO", label: "短视频" }]} value={draft.saleChannel} />
          <SelectField label="发票审核状态" onChange={(value) => setField("invoiceStatus", value)} options={invoiceStatusOptions} value={draft.invoiceStatus} />
          <SelectField label="结算状态" onChange={(value) => setField("settlementStatus", value)} options={[{ value: "", label: "全部状态" }, { value: "UNSETTLED", label: "未结算" }, { value: "SETTLED", label: "已结算" }]} value={draft.settlementStatus} />
        </div>
        <div className="finance-order-filters__row finance-order-filters__row--secondary">
          <fieldset className="finance-date-range-filter">
            <legend>发票提交日期范围</legend>
            <div><FieldInput aria-label="发票提交开始日期" onChange={(event) => setField("submittedFrom", event.target.value)} type="date" value={draft.submittedFrom} /><span aria-hidden="true">至</span><FieldInput aria-label="发票提交结束日期" onChange={(event) => setField("submittedTo", event.target.value)} type="date" value={draft.submittedTo} /></div>
          </fieldset>
          <fieldset className="finance-date-range-filter">
            <legend>核销日期范围</legend>
            <div><FieldInput aria-label="核销开始日期" onChange={(event) => setField("verifyFrom", event.target.value)} type="date" value={draft.verifyFrom} /><span aria-hidden="true">至</span><FieldInput aria-label="核销结束日期" onChange={(event) => setField("verifyTo", event.target.value)} type="date" value={draft.verifyTo} /></div>
          </fieldset>
          <div className="finance-order-filter-actions">
            <Button type="submit" variant="primary">应用筛选</Button>
            <Button onClick={resetFilters} variant="text">重置筛选</Button>
          </div>
        </div>
      </form>

      <ResourceNotice loading={resourceBusy} error={resource.error} />
      {exportMessage ? <p role={exportState === "error" ? "alert" : "status"}>{exportMessage}</p> : null}

      <section className="content-section">
        <div className="section-title"><div><h2>订单费用明细</h2><p>共 {total} 条，第 {page} / {pageCount} 页；双击任意行可查看完整冻结字段。</p></div></div>
        <DataTable columns={columns} emptyText="当前筛选下暂无订单明细" onRowAction={setSelectedRow} onRowDoubleClick={setSelectedRow} rowActionLabel={() => "查看完整字段"} rows={rows} state={resourceBusy ? "loading" : resource.error ? "error" : "ready"} stickyHeader="container" tableClassName="finance-order-table" />
        <TablePagination loading={resourceBusy} onPageChange={changePage} onPageSizeChange={onPageSizeChange} page={page} pageSize={pageSize} pageSizeOptions={[20, 50, 100, 200, 500]} rowsOnPage={rows.length} total={total} totalPages={pageCount} />
      </section>

      {selectedRow ? (
        <aside className="finance-detail-drawer" aria-label="订单完整字段">
          <header><div><p className="eyebrow">订单明细</p><h2>{selectedRow.orderId}</h2></div><Button onClick={() => setSelectedRow(null)} variant="text">关闭</Button></header>
          <FinanceOrderDetail row={selectedRow} />
        </aside>
      ) : null}

      <details className="content-section">
        <summary>字段来源与计算说明</summary>
        <dl>
          {Object.entries(resource.data?.data.definitions ?? {}).map(([field, definition]) => (
            <div key={field}><dt>{field}</dt><dd>{definition.description}（来源：{definition.source}）</dd></div>
          ))}
        </dl>
      </details>
    </div>
  );
}
