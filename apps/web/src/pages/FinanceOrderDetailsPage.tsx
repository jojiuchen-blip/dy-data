import { FormEvent, useState } from "react";
import { downloadFinanceOrderDetails, fetchFinanceOrderDetails } from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FieldInput, SelectField } from "../components/FormControls";
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
  month: string;
  storeId: string;
  storeName: string;
  sapCode: string;
  invoiceNumber: string;
  orderId: string;
  skuId: string;
  saleChannel: string;
  invoiceStatus: string;
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

function optionalDateTime(value: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined;
}

function makeQuery(
  feeDirection: FeeDirection,
  draft: FilterDraft,
  page: number,
): FinanceOrderDetailsQuery {
  return {
    month: draft.month,
    feeDirection,
    storeId: optional(draft.storeId),
    storeName: optional(draft.storeName),
    sapCode: optional(draft.sapCode),
    invoiceNumber: optional(draft.invoiceNumber),
    orderId: optional(draft.orderId),
    skuId: optional(draft.skuId),
    saleChannel: optional(draft.saleChannel),
    invoiceStatus: optional(draft.invoiceStatus),
    submittedFrom: optionalDateTime(draft.submittedFrom),
    submittedTo: optionalDateTime(draft.submittedTo),
    verifyFrom: optionalDateTime(draft.verifyFrom),
    verifyTo: optionalDateTime(draft.verifyTo),
    page,
    pageSize: draft.pageSize,
  };
}

function initialDraft(searchParams: URLSearchParams): FilterDraft {
  return {
    month: searchParams.get("month") ?? defaultStatementMonth(),
    storeId: searchParams.get("storeId") ?? "",
    storeName: "",
    sapCode: "",
    invoiceNumber: "",
    orderId: "",
    skuId: "",
    saleChannel: "",
    invoiceStatus: "",
    submittedFrom: "",
    submittedTo: "",
    verifyFrom: "",
    verifyTo: "",
    pageSize: 50,
  };
}

function FinanceOrderDetail({ row }: { row: FinanceOrderDetailRow }) {
  const money = (value: number | null) => value == null ? "-" : formatCurrency(value);
  const values = [
    ["分录 ID", row.statementEntryId],
    ["账单 ID", row.statementId],
    ["门店 ID", row.storeId],
    ["门店名称", row.storeName],
    ["SAP", row.sapCode],
    ["账期", row.statementMonth],
    ["费用方向", displayFeeDirection(row.feeDirection)],
    ["订单 ID", row.orderId],
    ["券 ID", row.couponId],
    ["订单状态", displayFinanceOrderStatus(row.orderStatus)],
    ["券状态", displayFinanceOrderStatus(row.couponStatus)],
    ["商品名称", row.productName],
    ["SKU ID", row.skuId],
    ["SKU 名称", row.skuName],
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
    ["发票状态", displayFinanceInvoiceStatus(row.invoiceStatus)],
    ["结算时间", formatDateTime(row.settledAt)],
    ["不通过原因", row.rejectionReason],
    ["导入时间", formatDateTime(row.importedAt)],
    ["结算状态", displayFinanceSettlementStatus(row.settlementStatus)],
    ["厂家扣款日期", row.factoryDeductionDate],
    ["厂家扣款金额", money(row.factoryDeductionAmountCent)],
  ];
  return (
    <details>
      <summary>查看完整字段</summary>
      <dl className="finance-order-detail-grid">
        {values.map(([label, value]) => (
          <div key={String(label)}><dt>{label}</dt><dd>{value ?? "-"}</dd></div>
        ))}
      </dl>
    </details>
  );
}

export function FinanceOrderDetailsPage({ feeDirection, searchParams }: FinanceOrderDetailsPageProps) {
  const [draft, setDraft] = useState<FilterDraft>(() => initialDraft(searchParams));
  const [query, setQuery] = useState<FinanceOrderDetailsQuery>(() =>
    makeQuery(feeDirection, initialDraft(searchParams), 1),
  );
  const [exportState, setExportState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [exportMessage, setExportMessage] = useState("");
  const queryKey = JSON.stringify(query);
  const resource = useApiResource(
    () => fetchFinanceOrderDetails(query),
    [queryKey],
  );
  const resourceBusy = resource.loading || resource.refreshing;
  const rows = resource.data?.data.list ?? [];
  const total = resource.data?.data.total ?? 0;
  const page = resource.data?.data.page ?? query.page ?? 1;
  const pageSize = resource.data?.data.pageSize ?? query.pageSize ?? 50;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const columns: Column<FinanceOrderDetailRow>[] = [
    { key: "order", title: "订单 / 券", minWidth: 190, sticky: true, render: (row) => <span><strong>{row.orderId}</strong><br /><small>{row.couponId ?? "-"}</small></span> },
    { key: "store", title: "服务店 / SAP", minWidth: 190, render: (row) => <span>{row.storeName ?? row.storeId}<br /><small>{row.sapCode ?? "-"}</small></span> },
    { key: "product", title: "商品 / SKU", minWidth: 180, render: (row) => <span>{row.productName ?? "-"}<br /><small>{row.skuName ?? row.skuId ?? "-"}</small></span> },
    { key: "channel", title: "销售渠道", render: (row) => displayFinanceSaleChannel(row.saleChannel) },
    { key: "verify", title: "核销时间", minWidth: 170, render: (row) => formatDateTime(row.verifyTime) },
    { key: "received", title: "实收金额", align: "right", render: (row) => row.receivedAmountCent == null ? "-" : formatCurrency(row.receivedAmountCent) },
    { key: "base", title: "冻结计费基数", align: "right", render: (row) => formatCurrency(row.frozenFeeBaseCent) },
    { key: "rate", title: "实际费率", align: "right", render: (row) => row.actualFeeRate ?? "-" },
    { key: "fee", title: feeDirection === "PROMOTION" ? "推广服务费" : "管理服务费", align: "right", render: (row) => formatCurrency(row.frozenFeeAmountCent) },
    { key: "rowType", title: "行类型", render: (row) => displayFinanceOrderRowType(row.rowType) },
    { key: "invoice", title: "发票 / 结算", minWidth: 180, render: (row) => <span>{row.invoiceNumber ?? "-"}<br /><small>{feeDirection === "PROMOTION" ? displayFinanceInvoiceStatus(row.invoiceStatus) : displayFinanceSettlementStatus(row.settlementStatus)}</small></span> },
    { key: "details", title: "详情", minWidth: 150, render: (row) => <FinanceOrderDetail row={row} /> },
  ];

  const setField = <K extends keyof FilterDraft>(key: K, value: FilterDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const submitFilters = (event: FormEvent) => {
    event.preventDefault();
    setQuery(makeQuery(feeDirection, draft, 1));
  };

  const resetFilters = () => {
    const reset = initialDraft(new URLSearchParams());
    setDraft(reset);
    setQuery(makeQuery(feeDirection, reset, 1));
    setExportState("idle");
    setExportMessage("");
  };

  const changePage = (nextPage: number) => {
    setQuery((current) => ({ ...current, page: nextPage }));
  };

  const changePageSize = (nextPageSize: number) => {
    setDraft((current) => ({ ...current, pageSize: nextPageSize }));
    setQuery((current) => ({ ...current, page: 1, pageSize: nextPageSize }));
  };

  const handleExport = async () => {
    setExportState("loading");
    setExportMessage("导出中，请稍候。");
    try {
      const { page: _page, pageSize: _pageSize, ...exportQuery } = query;
      const result = await downloadFinanceOrderDetails(exportQuery);
      setExportState("success");
      setExportMessage(
        result.result === "EMPTY"
          ? "筛选结果为空，已下载仅含表头的文件。"
          : `导出成功：${result.fileName}`,
      );
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
          <p>原费用与退款/取消调整分别成行；列表、总数和导出统一使用后端冻结事实。</p>
        </div>
        <Button loading={exportState === "loading"} onClick={handleExport} variant="primary">
          {exportState === "loading" ? "导出中" : "导出全部命中结果"}
        </Button>
      </section>

      <form className="finance-filter-bar" aria-label="订单明细筛选条件" onSubmit={submitFilters}>
        <label><span>账期</span><FieldInput type="month" value={draft.month} onChange={(event) => setField("month", event.target.value)} /></label>
        <label><span>门店 ID</span><FieldInput value={draft.storeId} onChange={(event) => setField("storeId", event.target.value)} /></label>
        <label><span>门店名称</span><FieldInput value={draft.storeName} onChange={(event) => setField("storeName", event.target.value)} /></label>
        <label><span>SAP</span><FieldInput value={draft.sapCode} onChange={(event) => setField("sapCode", event.target.value)} /></label>
        <label><span>发票号</span><FieldInput value={draft.invoiceNumber} onChange={(event) => setField("invoiceNumber", event.target.value)} /></label>
        <label><span>订单 ID</span><FieldInput value={draft.orderId} onChange={(event) => setField("orderId", event.target.value)} /></label>
        <label><span>SKU ID</span><FieldInput value={draft.skuId} onChange={(event) => setField("skuId", event.target.value)} /></label>
        <label><span>销售渠道</span><FieldInput value={draft.saleChannel} onChange={(event) => setField("saleChannel", event.target.value)} /></label>
        <SelectField
          label={feeDirection === "PROMOTION" ? "审核/结算状态" : "结算状态"}
          onChange={(value) => setField("invoiceStatus", value)}
          options={feeDirection === "PROMOTION" ? [
            { value: "", label: "全部" },
            { value: "PENDING_INVOICE", label: "待开票" },
            { value: "SUBMITTED_PENDING_FACTORY_REVIEW", label: "提交成功，待厂端审核" },
            { value: "APPROVED_SETTLED", label: "审核通过，已结算" },
            { value: "REJECTED_REUPLOAD", label: "审核不通过，请重新上传" },
          ] : [
            { value: "", label: "全部" },
            { value: "SETTLED", label: "已结算" },
            { value: "UNSETTLED", label: "未结算" },
          ]}
          value={draft.invoiceStatus}
        />
        <label><span>提交时间起</span><FieldInput type="datetime-local" value={draft.submittedFrom} onChange={(event) => setField("submittedFrom", event.target.value)} /></label>
        <label><span>提交时间止</span><FieldInput type="datetime-local" value={draft.submittedTo} onChange={(event) => setField("submittedTo", event.target.value)} /></label>
        <label><span>核销时间起</span><FieldInput type="datetime-local" value={draft.verifyFrom} onChange={(event) => setField("verifyFrom", event.target.value)} /></label>
        <label><span>核销时间止</span><FieldInput type="datetime-local" value={draft.verifyTo} onChange={(event) => setField("verifyTo", event.target.value)} /></label>
        <div className="finance-form-actions">
          <Button type="submit" variant="primary">应用筛选</Button>
          <Button onClick={resetFilters} variant="text">重置筛选</Button>
        </div>
      </form>

      <ResourceNotice loading={resource.loading} error={resource.error} />
      {exportMessage ? <p role={exportState === "error" ? "alert" : "status"}>{exportMessage}</p> : null}

      <section className="content-section">
        <div className="section-title">
          <div><h2>订单费用明细</h2><p>共 {total} 条，第 {page} / {pageCount} 页。</p></div>
        </div>
        <DataTable columns={columns} rows={rows} state={resourceBusy ? "loading" : resource.error ? "error" : "ready"} stickyHeader="container" />
        <TablePagination loading={resourceBusy} onPageChange={changePage} onPageSizeChange={changePageSize} page={page} pageSize={pageSize} pageSizeOptions={[20, 50, 100, 200, 500]} rowsOnPage={rows.length} total={total} totalPages={pageCount} />
      </section>

      <details className="content-section">
        <summary>字段来源与计算说明</summary>
        <dl>
          {Object.entries(resource.data?.data.definitions ?? {}).map(([field, definition]) => (
            <div key={field}>
              <dt>{field}</dt>
              <dd>{definition.description}（来源：{definition.source}）</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}
