import { useState } from "react";
import { ApiRequestError, correctManagementInvoice, fetchFinanceInvoices, fetchFinanceSummary } from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { FinanceImportActionPanel } from "../components/FinanceImportActionPanel";
import { FieldInput } from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import { useApiResource } from "../hooks/useApiResource";
import type {
  BillingMetricScope,
  FeeDirection,
  FinanceInvoiceRow,
} from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { userFacingError } from "../utils/userFacingError";
import { displayFinanceInvoiceStatus } from "../utils/userFacingLabels";

interface FinanceFeePageProps {
  feeDirection: FeeDirection;
  searchParams: URLSearchParams;
}

function defaultStatementMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function financeInvoiceStatusLabel(status: string, direction: FeeDirection): string {
  if (direction === "MANAGEMENT") {
    return ({
      PENDING_INVOICE: "待开票",
      APPROVED_SETTLED: "已开票 / 已扣款",
      REJECTED_REUPLOAD: "待重新导入",
    } as Record<string, string>)[status] ?? "未知发票 / 扣款状态";
  }
  return displayFinanceInvoiceStatus(status);
}

export function FinanceFeePage({ feeDirection, searchParams }: FinanceFeePageProps) {
  const [month, setMonth] = useState(searchParams.get("month") ?? defaultStatementMonth());
  const [storeId, setStoreId] = useState(searchParams.get("storeId") ?? "");
  const [metricScope, setMetricScope] = useState<BillingMetricScope>("MONTH");
  const [showHistory, setShowHistory] = useState(false);
  const [correction, setCorrection] = useState<null | {
    row: FinanceInvoiceRow;
    invoiceNumber: string;
    invoiceDate: string;
    invoiceAmountCent: string;
    deductionDate: string;
    deductionAmountCent: string;
    changeReason: string;
    idempotencyKey: string;
  }>(null);
  const [correctionState, setCorrectionState] = useState<"idle" | "loading" | "success" | "error" | "conflict">("idle");
  const [correctionMessage, setCorrectionMessage] = useState("");
  const title = feeDirection === "PROMOTION" ? "推广服务费" : "管理服务费";

  const summaryResource = useApiResource(
    () => fetchFinanceSummary({ month, feeDirection, metricScope, storeId: storeId || undefined }),
    [month, feeDirection, metricScope, storeId],
  );
  const invoiceResource = useApiResource(
    () => fetchFinanceInvoices({ month, feeDirection, storeId: storeId || undefined, includeHistory: feeDirection === "MANAGEMENT" && showHistory, pageSize: 50 }),
    [month, feeDirection, storeId, showHistory],
  );
  const metrics = summaryResource.data?.data.metrics;
  const rows = invoiceResource.data?.data.list ?? [];

  const columns: Column<FinanceInvoiceRow>[] = [
    { key: "store", title: "门店 ID", minWidth: 150, render: (row) => row.storeId },
    { key: "month", title: "账期", render: (row) => row.statementMonth },
    { key: "number", title: "发票号码", minWidth: 210, render: (row) => row.invoiceNumber },
    { key: "date", title: "开票日期", render: (row) => row.invoiceDate },
    { key: "amount", title: feeDirection === "PROMOTION" ? "已开票金额" : "厂家扣款金额", align: "right", render: (row) => formatCurrency(row.invoiceAmountCent) },
    { key: "status", title: "状态", render: (row) => financeInvoiceStatusLabel(row.status, feeDirection) },
    { key: "time", title: "导入时间", minWidth: 170, render: (row) => formatDateTime(row.registeredAt) },
    ...(feeDirection === "MANAGEMENT" ? [{
      key: "action",
      title: "操作",
      render: (row: FinanceInvoiceRow) => row.isCurrent ? <Button size="sm" variant="text" onClick={() => {
        setCorrection({
          row,
          invoiceNumber: row.invoiceNumber,
          invoiceDate: row.invoiceDate,
          invoiceAmountCent: String(row.invoiceAmountCent),
          deductionDate: row.factoryDeductionDate ?? row.invoiceDate,
          deductionAmountCent: String(
            row.factoryDeductionAmountCent ?? row.invoiceAmountCent,
          ),
          changeReason: "",
          idempotencyKey: crypto.randomUUID(),
        });
        setCorrectionState("idle");
        setCorrectionMessage("");
      }}>更正</Button> : <span>历史 V{row.versionNo}</span>,
    } as Column<FinanceInvoiceRow>] : []),
  ];

  const submitCorrection = async () => {
    if (!correction || !correction.changeReason.trim()) return;
    setCorrectionState("loading");
    setCorrectionMessage("");
    try {
      await correctManagementInvoice(
        correction.row.storeId,
        correction.row.statementMonth,
        {
          invoiceNumber: correction.invoiceNumber,
          invoiceDate: correction.invoiceDate,
          invoiceAmountCent: Number(correction.invoiceAmountCent),
          deductionDate: correction.deductionDate,
          deductionAmountCent: Number(correction.deductionAmountCent),
          changeReason: correction.changeReason.trim(),
          readVersion: correction.row.versionNo,
        },
        correction.idempotencyKey,
      );
      setCorrectionState("success");
      setCorrectionMessage("更正已立即生效，并保留原历史版本。");
      summaryResource.reload();
      invoiceResource.reload();
    } catch (error) {
      const message = userFacingError(error, "更正失败，请重试。");
      const conflict = error instanceof ApiRequestError && error.status === 409;
      setCorrectionState(conflict ? "conflict" : "error");
      setCorrectionMessage(conflict ? "版本已变化，请刷新当前版本后重新提交。" : message);
    }
  };

  return (
    <div className="page-stack finance-page">
      <section className="page-heading finance-heading">
        <div>
          <p className="eyebrow">财务管理员</p>
          <h1>{title}</h1>
          <p>{feeDirection === "PROMOTION" ? "查询门店登记信息及管理员导入后的审核、结算状态。" : "管理员按当期导入上月管理服务费发票明细；导入即表示外部流程已完成。"}</p>
        </div>
      </section>
      <section className="finance-filter-bar" aria-label="财务筛选条件">
        <label><span>账期</span><FieldInput type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
        <label><span>门店 ID（可选）</span><FieldInput value={storeId} onChange={(event) => setStoreId(event.target.value)} /></label>
        <label>
          <span>指标口径</span>
          <SearchableStoreSelect
            emptyMessage="未找到指标口径"
            onChange={(value) => setMetricScope(value as BillingMetricScope)}
            options={[
              { value: "MONTH", label: "单月" },
              { value: "CUMULATIVE", label: "累计" },
            ]}
            placeholder="选择指标口径"
            value={metricScope}
          />
        </label>
      </section>
      <ResourceNotice loading={summaryResource.loading || invoiceResource.loading} error={summaryResource.error ?? invoiceResource.error} />
      <section className="metric-grid finance-metric-grid">
        <MetricCard label="账单总额" value={formatCurrency(metrics?.statementTotalCent ?? 0)} />
        <MetricCard label="已确认金额" value={formatCurrency(metrics?.confirmedAmountCent ?? 0)} />
        <MetricCard label="待开票金额" value={formatCurrency(metrics?.pendingInvoiceAmountCent ?? 0)} />
        <MetricCard label={feeDirection === "PROMOTION" ? "已开票金额" : "厂家扣款金额"} value={formatCurrency(metrics?.issuedAmountCent ?? 0)} />
        <MetricCard label="已结算/扣款金额" value={formatCurrency(metrics?.settledOrDeductedAmountCent ?? 0)} />
      </section>
      <section className="content-section">
        <div className="section-title"><div><h2>{feeDirection === "PROMOTION" ? "推广费发票明细" : "管理服务费发票与扣款明细"}</h2><p>系统内不设置额外审核节点，只保留查询、导出和操作审计所需记录。</p></div>{feeDirection === "MANAGEMENT" ? <Button variant="text" onClick={() => setShowHistory((value) => !value)}>{showHistory ? "仅看当前版本" : "查看历史版本"}</Button> : null}</div>
        <DataTable columns={columns} rows={rows} state={invoiceResource.loading ? "loading" : invoiceResource.error ? "error" : "ready"} />
      </section>
      {feeDirection === "MANAGEMENT" && correction ? <section className="content-section finance-correction-panel">
        <div className="section-title"><div><h2>更正管理服务费记录</h2><p>{correction.row.storeId} · {correction.row.statementMonth} · 当前 V{correction.row.versionNo}；金额可编辑，提交时将按版本校验并保留历史记录。</p></div><Button variant="text" onClick={() => setCorrection(null)}>关闭</Button></div>
        <div className="finance-filter-bar">
          <label><span>发票号码</span><FieldInput value={correction.invoiceNumber} onChange={(event) => setCorrection({ ...correction, invoiceNumber: event.target.value })} /></label>
          <label><span>发票日期</span><FieldInput type="date" value={correction.invoiceDate} onChange={(event) => setCorrection({ ...correction, invoiceDate: event.target.value })} /></label>
          <label><span>厂家扣款日期</span><FieldInput type="date" value={correction.deductionDate} onChange={(event) => setCorrection({ ...correction, deductionDate: event.target.value })} /></label>
          <label><span>发票金额（分）</span><FieldInput aria-label="发票金额（分）" type="number" min="1" step="1" value={correction.invoiceAmountCent} onChange={(event) => setCorrection({ ...correction, invoiceAmountCent: event.target.value })} /></label>
          <label><span>厂家扣款金额（分）</span><FieldInput aria-label="厂家扣款金额（分）" type="number" min="1" step="1" value={correction.deductionAmountCent} onChange={(event) => setCorrection({ ...correction, deductionAmountCent: event.target.value })} /></label>
          <label><span>更正原因</span><FieldInput value={correction.changeReason} onChange={(event) => setCorrection({ ...correction, changeReason: event.target.value })} /></label>
        </div>
        {correctionMessage ? <p role={correctionState === "error" || correctionState === "conflict" ? "alert" : "status"}>{correctionMessage}</p> : null}
        <Button disabled={correctionState === "loading" || !correction.changeReason.trim()} onClick={submitCorrection}>{correctionState === "loading" ? "提交中…" : "确认更正"}</Button>
      </section> : null}
      <FinanceImportActionPanel
        scope={feeDirection}
        month={month}
        onCommitted={() => {
          summaryResource.reload();
          invoiceResource.reload();
        }}
      />
    </div>
  );
}
