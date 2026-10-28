import { useEffect, useState } from "react";
import { fetchFinanceImportPreview } from "../api/client";
import { useApiResource } from "../hooks/useApiResource";
import type { FinanceImportPreviewRow, FinanceImportPreviewValue } from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { Button } from "./Button";
import { DataTable, type Column } from "./DataTable";
import { ResourcePanel } from "./ResourceState";
import { TablePagination } from "./TablePagination";

const fieldLabels: Record<string, string> = {
  storeId: "门店编号", storeName: "门店名称", sapCode: "SAP 编码", importedAt: "导入时间",
  financeInitialSap: "财务初始 SAP", serviceStoreCode: "服务门店编码", finalSapCode: "最终 SAP 编码",
  factoryConfirmationResult: "厂家确认结果", confirmedAt: "确认时间", invoiceNumber: "发票号码",
  reviewResult: "审核结果", rejectionReason: "审核不通过原因", settlementDate: "结算日期",
  settlementAmountCent: "结算金额", statementMonth: "业务账期", invoiceDate: "开票日期",
  deductionDate: "扣款日期", deductionAmountCent: "扣款金额", invoiceStatus: "开票状态",
};

function displayValue(field: string, value: FinanceImportPreviewValue | undefined): string {
  if (value === undefined) return "未提供";
  if (value === null) return "空值（未记录）";
  if (value === "") return "空文本";
  if (typeof value === "string" && ["reviewResult", "factoryConfirmationResult", "invoiceStatus"].includes(field)) return displayState(value);
  if (typeof value === "number" && field.endsWith("AmountCent")) return formatCurrency(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string" && field.endsWith("At") && !Number.isNaN(Date.parse(value))) return formatDateTime(value);
  return String(value);
}

function displayState(value: string | null): string {
  if (value === null) return "未记录状态";
  const labels: Record<string, string> = {
    PENDING_INVOICE: "待开票", SUBMITTED_PENDING_FACTORY_REVIEW: "待厂家审核",
    APPROVED_SETTLED: "审核通过，已结算", REJECTED_REUPLOAD: "审核不通过，待重新上传",
    INVOICED: "已开票", NOT_INVOICED: "未开票", CONFIRMED: "已确认", PENDING: "待处理",
    CURRENT_PROFILE: "当前有效档案", REJECTED: "确认不通过",
    TOMBSTONE: "已撤销，无有效资料",
  };
  return labels[value] ?? (/^[A-Z0-9_]+$/.test(value) ? "状态待核查" : value);
}

export function FinanceImportPreviewTable({ batchId, onReadinessChange }: {
  batchId: string;
  onReadinessChange?: (batchId: string, ready: boolean) => void;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const resource = useApiResource(
    () => fetchFinanceImportPreview(batchId, { page, pageSize }),
    [batchId, page, pageSize], { clearOnReload: true },
  );
  const busy = resource.loading || resource.refreshing;
  const data = resource.data?.data;
  const summary = data?.previewSummary;
  const ready = !busy && !resource.error && Boolean(summary?.frozenAvailable
    && summary.blockedRowCount === 0 && summary.totalRows > 0 && data?.list.length
    && data.list.every((row) => row.preview.available && row.preview.stateTransition.allowed && !row.preview.blockedReasons.length));
  useEffect(() => { onReadinessChange?.(batchId, ready); }, [batchId, ready, onReadinessChange]);

  const columns: Column<FinanceImportPreviewRow>[] = [
    { key: "row", title: "原文件行号", minWidth: 100, render: (row) => row.rowNumber },
    { key: "business", title: "门店 / 发票业务标识", minWidth: 200, render: (row) => row.businessKey },
    { key: "changes", title: "字段：原值 → 新值", minWidth: 320, render: (row) => {
      if (!row.preview.available) return <span>{row.preview.reason}</span>;
      const { before, after } = row.preview;
      const fields = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after)])];
      const missingBefore = row.preview.targetTombstone ? "原资料已撤销" : "原记录不存在";
      return <div>{before === null ? <p>{missingBefore}（新增有效资料）</p> : null}{fields.map((field) => <div key={field}>
        <strong>{fieldLabels[field] ?? "其他业务字段"}{before !== null && before[field] === after[field] ? "（未变）" : "（变更）"}</strong>：{before === null ? missingBefore : displayValue(field, before[field])}
        {" → "}{displayValue(field, after[field])}
      </div>)}</div>;
    } },
    { key: "state", title: "状态变化 / 允许修改范围", minWidth: 260, render: (row) => {
      if (!row.preview.available) return "无法核对，请重新上传";
      const { stateTransition: transition, allowedChanges } = row.preview;
      return <div><p>{displayState(transition.fromState)} → {displayState(transition.toState)}</p>
        <strong>{transition.allowed ? "允许本次变更" : "本次变更被阻断"}</strong>
        {allowedChanges.map((item, index) => <div key={index}>{item}</div>)}</div>;
    } },
    { key: "blocked", title: "阻断原因", minWidth: 220, render: (row) => !row.preview.available
      ? "未保存上传时预览，请重新上传" : row.preview.blockedReasons.length
        ? row.preview.blockedReasons.map((reason, index) => <div key={index}>{reason}</div>) : "无" },
  ];
  return <section className="records-section finance-import-field-preview" aria-label="逐行字段预览">
    <div className="section-title"><div><h3>逐行字段预览</h3><p>以下原值保留自上传时；显示完整字段便于核对。空值、空文本和未提供分别展示。</p></div></div>
    {busy ? <ResourcePanel>正在加载逐行预览…</ResourcePanel> : null}
    {resource.error ? <ResourcePanel tone="error">{userFacingError(resource.rawError, "逐行预览读取失败，请重试。")}
      <Button onClick={resource.reload} variant="secondary">重试预览</Button></ResourcePanel> : null}
    {!busy && !resource.error && data && !summary?.frozenAvailable ? <ResourcePanel tone="error">此批次未保存完整字段预览，请重新上传；当前业务数据不能替代上传时原值。</ResourcePanel> : null}
    {summary && summary.blockedRowCount > 0 ? <ResourcePanel tone="error">整批共有 {summary.blockedRowCount} 行被阻断，请修正后重新上传。</ResourcePanel> : null}
    <DataTable columns={columns} rows={busy || resource.error ? [] : data?.list ?? []}
      state={busy ? "loading" : resource.error ? "error" : "ready"}
      emptyText="本批次没有可展示的预览行" loadingText="正在加载逐行预览…" errorText="逐行预览暂不可用" />
    {data && !busy && !resource.error && data.list.length === 0 && page > 1 ? <Button variant="secondary" onClick={() => setPage(1)}>返回预览首页</Button> : null}
    {data && !resource.error && data.list.length > 0 ? <TablePagination loading={busy} onPageChange={(next) => {
      if (next === page) return;
      onReadinessChange?.(batchId, false); setPage(next);
    }}
      onPageSizeChange={(size) => {
        if (size === pageSize && page === 1) return;
        onReadinessChange?.(batchId, false); setPageSize(size); setPage(1);
      }} page={data.page} pageSize={data.pageSize}
      pageSizeOptions={[20, 50]} rowsOnPage={data.list.length} total={data.total}
      totalPages={Math.max(1, Math.ceil(data.total / data.pageSize))} /> : null}
  </section>;
}
